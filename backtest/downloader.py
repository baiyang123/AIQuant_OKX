import os
import sys
import time
import ccxt
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量 (主要是为了获取代理配置，如果需要的话)
load_dotenv(override=True)

def get_proxy_config():
    """尝试从环境变量获取代理配置"""
    proxy_url = os.getenv('HTTP_PROXY')
    if proxy_url:
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    return None

def download_history(symbol, timeframe, start_str, end_str):
    """
    下载历史 K 线数据并保存为 CSV
    :param symbol: 交易对，如 'BTC/USDT:USDT'
    :param timeframe: 周期，如 '4h', '1d', '15m'
    :param start_str: 开始时间，格式 'YYYY-MM-DD'
    :param end_str: 结束时间，格式 'YYYY-MM-DD' (或 'now')
    """
    
    # 1. 初始化交易所 (只用于下载数据，不需要 API Key)
    exchange = ccxt.okx({
        'enableRateLimit': True, # 启用速率限制，防止被封 IP
        'proxies': get_proxy_config()
    })

    # 2. 转换时间戳 (毫秒)
    try:
        since = exchange.parse8601(f"{start_str} 00:00:00")
        if end_str == 'now':
            end_timestamp = exchange.milliseconds()
        else:
            end_timestamp = exchange.parse8601(f"{end_str} 00:00:00")
    except Exception as e:
        print(f"❌ 时间格式错误: {e}")
        return

    print(f"📥 开始下载 {symbol} [{timeframe}]")
    print(f"   时间范围: {start_str} -> {end_str}")
    print(f"   使用代理: {get_proxy_config() is not None}")

    all_candles = []
    retry_count = 0
    
    # 3. 分页循环下载
    while since < end_timestamp:
        try:
            # OKX 单次限制通常为 100 或 300，limit=100 比较保守安全
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=100)
            
            if not candles:
                print("⚠️ 未获取到数据，可能已到达当前时间或数据中断，停止下载。")
                break

            # 获取当前批次最后一条的时间
            last_time = candles[-1][0]
            
            # 如果获取的数据时间没有推进，说明已经下完了或者卡住了
            if last_time == since:
                break
                
            all_candles += candles
            
            # 更新下一次下载的起点：最后一条数据的时间 + 1毫秒 (防止重叠，pandas后续会再次去重)
            since = last_time + 1
            
            # 打印进度
            current_date = datetime.fromtimestamp(last_time / 1000).strftime('%Y-%m-%d')
            print(f"   ... 已下载至 {current_date} (累计 {len(all_candles)} 条)")
            
            # 重置重试计数
            retry_count = 0
            
            # 稍微休眠一下，虽然 enableRateLimit 会自动处理，但手动加点延迟更稳
            time.sleep(exchange.rateLimit / 1000)

        except Exception as e:
            print(f"❌ 网络请求出错: {e}")
            retry_count += 1
            if retry_count > 3:
                print("❌ 重试次数过多，下载中止。")
                break
            time.sleep(2) # 出错后等待

    # 4. 数据清洗与存储
    if not all_candles:
        print("❌ 未下载到任何数据。")
        return

    print("🧹 正在清洗数据...")
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # 转换时间戳为可读日期
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # 过滤掉超出 end_timestamp 的部分(因为 fetch 可能会多拿一点)
    df = df[df['timestamp'] < end_timestamp]

    # 去重 (按时间戳)
    df = df.drop_duplicates(subset=['timestamp'], keep='last')
    
    # 排序
    df = df.sort_values('timestamp').reset_index(drop=True)

    # 5. 生成文件名 (替换特殊字符)
    # BTC/USDT:USDT -> BTC_USDT_USDT
    safe_symbol = symbol.replace('/', '_').replace(':', '_')
    
    # 确保目录存在
    save_dir = 'data/history'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    file_path = f"{save_dir}/{safe_symbol}_{timeframe}.csv"
    
    # 保存 CSV (不带索引)
    df.to_csv(file_path, index=False)
    
    print(f"✅ 下载完成！")
    print(f"   文件路径: {file_path}")
    print(f"   数据行数: {len(df)}")
    print(f"   时间范围: {df['datetime'].iloc[0]} -> {df['datetime'].iloc[-1]}")

# ==========================================
# 入口测试
# ==========================================
if __name__ == '__main__':
    # 示例：下载 BTC 永续合约数据
    
    TARGET_SYMBOL = 'BTC/USDT:USDT'  # 永续合约
    # TARGET_SYMBOL = 'BTC/USDT'     # 现货
    
    TIMEFRAME = '4h'
    START_DATE = '2025-01-01'
    END_DATE = '2025-03-01' # 或者指定日期 '2023-12-31'
    
    download_history(TARGET_SYMBOL, TIMEFRAME, START_DATE, END_DATE)