import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

class Config:
    """
    全局配置类 (OKX 合约版)
    """
    
    # ==========================
    # 1. 基础环境配置
    # ==========================
    TRADING_MODE = os.getenv('TRADING_MODE', 'DEMO').upper()
    DB_PATH = 'data/trade.db'

    # ==========================
    # 2. 默认交易参数 (全局缺省值)
    # ==========================
    # 交易对格式说明:
    # - 现货: 'BTC/USDT'
    # - 永续合约: 'BTC/USDT:USDT' (推荐)
    # - 交割合约: 'BTC/USDT-240329'
    SYMBOL = 'BTC/USDT:USDT' 
    
    TIMEFRAME = '4h'
    AMOUNT = 0.001           # 合约通常以"张"或"币"为单位，OKX USDT合约通常以币为单位
    
    # --- 合约特有参数 ---
    LEVERAGE = 5             # 默认杠杆倍数
    MARGIN_MODE = 'cross'    # 保证金模式: 'cross'(全仓) 或 'isolated'(逐仓)
    SIZE_MODE = 'PERCENT_BALANCE'  # 下单模式: 'PERCENT_BALANCE' 或 'AMOUNT'
    SIZE_VALUE = 0.5         # 下单量占比 (如 0.5 表示 50% 余额)

    # ==========================
    # 3. 消息推送配置
    # ==========================
    DINGTALK_TOKEN = os.getenv('DINGTALK_TOKEN')
    DINGTALK_SECRET = os.getenv('DINGTALK_SECRET')
    
    FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK')
    FEISHU_SECRET = os.getenv('FEISHU_SECRET')

    # ==========================
    # 4. 代理配置
    # ==========================
    _proxy_url = os.getenv('HTTP_PROXY')
    PROXIES = {
        'http': _proxy_url,
        'https': _proxy_url
    } if _proxy_url else None

    # ==========================
    # 5. API 密钥加载
    # ==========================
    API_KEY = None
    SECRET = None
    PASSPHRASE = None
    IS_SANDBOX = False

    @classmethod
    def load_api_keys(cls):
        """加载 API Key"""
        if cls.TRADING_MODE == 'REAL':
            print("⚠️ 【警告】当前处于实盘交易模式 (REAL) ⚠️")
            cls.API_KEY = os.getenv('OKX_REAL_API_KEY')
            cls.SECRET = os.getenv('OKX_REAL_SECRET')
            cls.PASSPHRASE = os.getenv('OKX_REAL_PASSPHRASE')
            cls.IS_SANDBOX = False
        else:
            print("✅ 当前处于模拟盘模式 (DEMO)")
            cls.API_KEY = os.getenv('OKX_DEMO_API_KEY')
            cls.SECRET = os.getenv('OKX_DEMO_SECRET')
            cls.PASSPHRASE = os.getenv('OKX_DEMO_PASSPHRASE')
            cls.IS_SANDBOX = True

        if not all([cls.API_KEY, cls.SECRET, cls.PASSPHRASE]):
            print(f"❌ 错误：检测到 {cls.TRADING_MODE} 模式下 API 配置缺失。")
            sys.exit(1)

    # ==========================
    # 6. CCXT 初始化配置 (核心修改)
    # ==========================
    @classmethod
    def get_ccxt_config(cls):
        """
        返回传给 ccxt.okx() 的配置字典
        """
        config = {
            'apiKey': cls.API_KEY,
            'secret': cls.SECRET,
            'password': cls.PASSPHRASE,
            'enableRateLimit': True,
            'options': {
                # [关键修改] 默认为 swap (永续合约)
                # 如果设为 'spot' 则为现货
                'defaultType': 'swap', 
            }
        }
        
        if cls.IS_SANDBOX:
            config['sandbox'] = True

        if cls.PROXIES:
            config['proxies'] = cls.PROXIES
            
        return config

    # ==========================
    # 7. 多策略配置 (合约示例)
    # ==========================
    ACTIVE_STRATEGIES = [
        {
            'id': 'BTC_TREND_01',
            'strategy': 'DOUBLE_MA',
            'symbol': 'BTC/USDT:USDT', # 注意使用合约符号
            'timeframe': '4h',
            'amount': 0.01,            # 下单数量 (BTC)
            'leverage': 5,             # 该策略特定杠杆
            'margin_mode': 'cross',    # 该策略特定模式
            'max_buys': 1,
            'size_mode': 'PERCENT_BALANCE', # 百分比 'PERCENT_BALANCE'固定'FIXED_MARGIN'
            'size_value': 0.5
        },
        # {
        #     'id': 'ETH_GRID_01',
        #     'strategy': 'DOUBLE_MA',
        #     'symbol': 'ETH/USDT:USDT',
        #     'timeframe': '15m',
        #     'amount': 0.1,
        #     'leverage': 3,
        #     'margin_mode': 'isolated',
        #     'max_buys': 5
        # }
    ]

# 自动加载 Key
Config.load_api_keys()