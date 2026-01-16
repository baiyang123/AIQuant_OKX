import sys
import time
import logging
import signal
from logging.handlers import TimedRotatingFileHandler

# 引入核心组件
from config import Config
from src.database import DatabaseHandler
from src.exchange import ExchangeClient
from src.notification import Notifier
from src.strategies import load_strategies  # 引入策略工厂

# ==========================================
# 1. 日志配置 (Logging Setup)
# ==========================================
def setup_logger():
    """
    配置全局日志：
    - 输出到控制台
    - 输出到文件 (logs/trading_bot.log)，每天轮转
    """
    import os
    if not os.path.exists("logs"):
        os.makedirs("logs")

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 文件处理器 (每天午夜切割，保留30天)
    file_handler = TimedRotatingFileHandler(
        filename="logs/trading_bot.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 根记录器配置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # 屏蔽第三方库的繁琐日志
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("ccxt").setLevel(logging.WARNING)

# ==========================================
# 2. 优雅退出机制
# ==========================================
def signal_handler(sig, frame):
    print("\n🛑 接收到退出信号，系统正在关闭...")
    Notifier.send_feishu("🛑 量化系统已停止运行 (人工停止)")
    sys.exit(0)

# ==========================================
# 3. 主程序入口
# ==========================================
def main():
    # 1. 初始化日志
    setup_logger()
    logger = logging.getLogger('Main')
    logger.info("🎬 系统正在启动...")

    # 注册退出信号 (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # 2. 初始化基础设施
        # 数据库 (自动建表)
        db = DatabaseHandler(Config.DB_PATH)
        
        # 交易所 (建立连接, 加载市场, 设置杠杆)
        exchange = ExchangeClient()
        
        # 通知模块 (无需实例化，使用静态方法)
        # 验证配置是否正确
        if not Config.FEISHU_WEBHOOK:
            logger.warning("⚠️ 未配置飞书 Webhook，将无法收到手机推送")

        # 3. 初始化策略池
        # 使用工厂模式，从 config.py 的 ACTIVE_STRATEGIES 列表中加载
        logger.info("🛠 正在加载策略...")
        strategies = load_strategies(exchange, db)
        
        if not strategies:
            logger.error("❌ 未加载任何策略，请检查 config.py 配置。程序退出。")
            return

        logger.info(f"✅ 成功加载 {len(strategies)} 个策略")
        
        # 4. 发送启动通知
        start_msg = f"🚀 量化交易系统已启动\n模式: {Config.TRADING_MODE}\n加载策略数: {len(strategies)}"
        Notifier.send_feishu(start_msg)

        # 5. 进入主循环 (Main Loop)
        logger.info("⚡ 交易循环已开始 (按 Ctrl+C 退出)")
        
        while True:
            for strategy in strategies:
                try:
                    # 执行策略逻辑 (获取数据 -> 分析 -> 交易)
                    strategy.run()
                    
                except Exception as e:
                    # 捕获单个策略的运行错误，防止整个程序崩溃
                    error_msg = f"❌ 策略 [{strategy.strategy_id}] 运行异常: {e}"
                    logger.error(error_msg, exc_info=True)
                    Notifier.send_feishu(error_msg, is_error=True)
            
            # 休眠等待 (每 60 秒轮询一次)
            # 建议不要低于 60 秒，以免触发交易所 API 频率限制
            time.sleep(60)

    except Exception as e:
        # 捕获主线程的致命错误
        critical_msg = f"❌ 系统发生致命错误，已崩溃: {e}"
        logger.critical(critical_msg, exc_info=True)
        Notifier.send_feishu(critical_msg, is_error=True)
        raise e

if __name__ == "__main__":
    main()