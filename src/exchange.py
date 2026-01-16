import sys
import os

# 将项目根目录添加到 python path，以便能找到 config.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt
import time
import logging
from config import Config

# 配置日志
logger = logging.getLogger('Exchange')

class ExchangeClient:
    """
    交易所客户端封装 (OKX 合约版)
    功能：
    1. 连接 OKX Swap API
    2. 管理杠杆和保证金模式
    3. 查询合约持仓
    4. 统一处理网络重试
    """

    def __init__(self):
        """
        初始化交易所实例
        """
        # 1. 获取配置 (已包含 defaultType: swap)
        ccxt_config = Config.get_ccxt_config()
        
        try:
            self.exchange = ccxt.okx(ccxt_config)
            
            # 2. 加载市场信息 (获取合约面值、最小下单量等)
            self.exchange.load_markets()
            
            mode_str = "实盘 (REAL)" if not Config.IS_SANDBOX else "模拟盘 (SANDBOX)"
            logger.info(f"✅ 交易所连接成功 | 模式: {mode_str} | 合约模式")

            # 3. 初始化杠杆和模式 (遍历配置中的所有策略进行设置)
            # 这是一个“尽力而为”的操作，如果失败（例如已有持仓导致无法切换模式），只报错不崩溃
            self._init_leverage_for_strategies()
            
        except Exception as e:
            logger.error(f"❌ 交易所初始化失败: {e}")
            raise e

    def _init_leverage_for_strategies(self):
        """
        [内部方法] 为配置中的所有策略设置初始杠杆和模式
        """
        if not hasattr(Config, 'ACTIVE_STRATEGIES'):
            return

        for strat_conf in Config.ACTIVE_STRATEGIES:
            symbol = strat_conf['symbol']
            # 优先使用策略单独配置的杠杆，否则使用全局默认
            leverage = strat_conf.get('leverage', Config.LEVERAGE)
            margin_mode = strat_conf.get('margin_mode', Config.MARGIN_MODE)
            
            self.set_leverage(symbol, leverage, margin_mode)

    def _retry_wrapper(self, func, *args, **kwargs):
        """
        [通用] 自动重试机制
        """
        max_retries = 3
        delay = 2
        
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except ccxt.NetworkError as e:
                logger.warning(f"⚠️ 网络请求异常 ({i+1}/{max_retries}): {e}，{delay}秒后重试...")
                time.sleep(delay)
            except ccxt.ExchangeError as e:
                # 业务错误不重试 (如余额不足、参数错误)
                raise e
            except Exception as e:
                raise e
        
        raise ccxt.NetworkError(f"重试 {max_retries} 次后失败")

    def set_leverage(self, symbol, leverage, margin_mode='cross'):
        """
        设置杠杆倍数和保证金模式
        :param symbol: 交易对 (如 'BTC/USDT:USDT')
        :param leverage: 倍数 (int)
        :param margin_mode: 'cross'(全仓) 或 'isolated'(逐仓)
        """
        try:
            # OKX 特有参数: mgnMode
            params = {'mgnMode': margin_mode}
            
            # 调用 ccxt 的 set_leverage
            # 注意：某些交易所可能需要分别设置杠杆和模式，ccxt for okx 封装得较好
            self._retry_wrapper(
                self.exchange.set_leverage,
                leverage,
                symbol,
                params=params
            )
            logger.info(f"⚙️ 设置杠杆成功: {symbol} -> {margin_mode} {leverage}x")
            
        except ccxt.ExchangeError as e:
            logger.error(f"❌ 设置杠杆失败 [{symbol}]: {e}")
            logger.warning("提示: 如果该币种当前有持仓或挂单，可能无法切换保证金模式。")
        except Exception as e:
            logger.error(f"❌ 设置杠杆未知错误: {e}")

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        """获取K线"""
        return self._retry_wrapper(
            self.exchange.fetch_ohlcv, 
            symbol=symbol, 
            timeframe=timeframe, 
            limit=limit
        )

    def fetch_balance(self):
        """
        获取账户资产 (USDT 余额)
        :return: 包含 free, used, total 的字典
        """
        # 对于 swap，fetch_balance 通常返回资金账户或交易账户的保证金余额
        return self._retry_wrapper(self.exchange.fetch_balance)

    def get_available_balance(self, currency='USDT'):
        """
        获取可用保证金
        """
        try:
            bal = self.fetch_balance()
            return bal.get(currency, {}).get('free', 0.0)
        except Exception:
            return 0.0

    def fetch_current_positions(self, symbol):
        """
        获取特定币种的当前持仓
        :param symbol: 交易对
        :return: list [ {symbol, side, contracts, unrealizedPnl, ...} ]
        """
        try:
            # fetch_positions 返回的是一个列表，因为可能是双向持仓
            positions = self._retry_wrapper(self.exchange.fetch_positions, symbols=[symbol])
            
            # 过滤掉仓位为 0 的记录 (OKX 有时会返回 quantity=0 的历史记录)
            active_positions = [
                p for p in positions 
                if float(p['contracts']) > 0 or float(p['info']['pos']) != 0
            ]
            
            return active_positions
            
        except Exception as e:
            logger.error(f"❌ 获取持仓失败 [{symbol}]: {e}")
            return []

    def get_current_price(self, symbol):
        """获取最新成交价"""
        try:
            ticker = self._retry_wrapper(self.exchange.fetch_ticker, symbol=symbol)
            return ticker['last']
        except Exception:
            return None

        
    def create_order(self, symbol, type, side, amount, price=None, params={}):
        """
        [核心下单接口] 统一封装下单逻辑
        :param symbol: 交易对
        :param type: 'market' (市价) or 'limit' (限价)
        :param side: 'buy' or 'sell'
        :param amount: 数量
        :param price: 价格 (市价单填 None)
        :param params: 额外参数 (如 {'reduceOnly': True})
        :return: 订单详情字典
        """
        # 记录关键日志，方便排查
        logger.info(f"⚡ 准备下单: {side} {type} {amount} {symbol} | Price: {price} | Params: {params}")
        
        return self._retry_wrapper(
            self.exchange.create_order,
            symbol=symbol,
            type=type,
            side=side,
            amount=amount,
            price=price,
            params=params
        )

    def amount_to_precision(self, symbol, amount):
        """
        [辅助] 将数量调整为交易所允许的精度
        :param amount: 原始计算出的浮点数 (如 0.12345678)
        :return: 截断后的字符串或浮点数 (如 0.123)
        """
        # 这是一个本地计算方法，通常不需要网络重试
        # 但必须确保 load_markets() 已执行
        try:
            return self.exchange.amount_to_precision(symbol, amount)
        except Exception as e:
            logger.error(f"精度转换失败: {e}")
            # 如果失败，兜底返回原始值，但这可能会导致下单报错
            return amount
            
    def cancel_order(self, order_id, symbol):
        """
        [辅助] 撤单 (为未来网格策略预留)
        """
        return self._retry_wrapper(
            self.exchange.cancel_order,
            id=order_id,
            symbol=symbol
        )    
        # 测试代码
if __name__ == "__main__":
    try:
        client = ExchangeClient()
        test_symbol = Config.ACTIVE_STRATEGIES[0]['symbol']
        
        # 1. 测试获取价格
        price = client.get_current_price(test_symbol)
        print(f"💰 {test_symbol} 当前合约价格: {price}")
        
        # 2. 测试获取持仓
        positions = client.fetch_current_positions(test_symbol)
        if positions:
            print(f"📊 当前持仓: {positions[0]['side']} {positions[0]['contracts']} 张")
            print(f"   未实现盈亏: {positions[0]['unrealizedPnl']}")
        else:
            print("📊 当前无持仓")
            
        # 3. 测试可用保证金
        usdt_free = client.get_available_balance('USDT')
        print(f"💵 可用保证金: {usdt_free:.2f} USDT")

    except Exception as e:
        print(f"程序运行出错: {e}")