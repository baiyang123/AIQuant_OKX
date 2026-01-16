from abc import ABC, abstractmethod
import logging
import pandas as pd
import time
from config import Config
from src.notification import Notifier  # 导入通知模块

class BaseStrategy(ABC):
    """
    策略抽象基类 (Structure B: 全能管家版)
    职责：
    1. 统一管理下单流程 (风控 -> 计算 -> 执行 -> 记账 -> 通知)
    2. 提供高层语义接口 (open_long, close_position)
    """
    def __init__(self, exchange_client, db_handler, config_dict):
        self.exchange = exchange_client
        self.db = db_handler
        self.config = config_dict
        
        # 1. 身份绑定
        self.strategy_id = config_dict['id']

        self.symbol = config_dict['symbol']
        self.timeframe = config_dict['timeframe']
        
        # 2. 资金与风控参数
        self.leverage = config_dict.get('leverage', Config.LEVERAGE)
        self.size_mode = config_dict.get('size_mode', Config.SIZE_MODE)
        self.size_value = config_dict.get('size_value', Config.SIZE_VALUE)
        self.max_buys = config_dict.get('max_buys', 1)

        self.logger = logging.getLogger(f"Strat-{self.strategy_id}")
        # self.logger.info(f"初始化策略 {self.strategy_id} 配置: {config_dict}")


    @abstractmethod
    def run(self):
        """[必须实现] 策略主循环逻辑"""
        pass

    # ==========================================
    # 1. 数据与状态 (Data & State)
    # ==========================================
    
    def get_ohlcv_df(self, limit=100):
        """获取K线并转为DataFrame"""
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        if not ohlcv: return None
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_position_details(self):
        """查询数据库状态"""
        return self.db.get_position_details(self.symbol, self.strategy_id)

    def can_buy(self):
        """风控检查: 是否允许加仓"""
        details = self.get_position_details()
        return (details['pos_count'] < self.max_buys), details['pos_count']

    def calculate_quantity(self, price):
        """计算下单数量 (核心算法)"""
        try:
            # 1. 确定本金
            margin_usdt = 0.0
            if self.size_mode == 'PERCENT_BALANCE':
                balance = self.exchange.get_available_balance('USDT')
                if balance <= 0: return None
                margin_usdt = balance * self.size_value
            elif self.size_mode == 'FIXED_MARGIN':
                margin_usdt = self.size_value
            
            # 2. 最小金额检查
            if margin_usdt < 6:
                self.logger.warning(f"⚠️ 资金过小 ({margin_usdt:.2f}U)，忽略下单")
                return None

            # 3. 计算数量 (本金 * 杠杆 / 币价)
            raw_amount = (margin_usdt * self.leverage) / price
            
            # 4. 精度清洗 (调用 ExchangeClient 的封装方法)
            # amount_to_precision 返回的是 string，转 float
            return float(self.exchange.amount_to_precision(self.symbol, raw_amount))
            
        except Exception as e:
            self.logger.error(f"❌ 计算数量出错: {e}")
            return None

    # ==========================================
    # 2. 核心交易动作 (Core Actions) - Structure B 核心
    # ==========================================

    def open_long(self, price):
        """
        [高层接口] 开多 / 加多
        """
        # 1. 风控检查
        allowed, count = self.can_buy()
        if not allowed:
            self.logger.info(f"🚫 达到最大持仓限制 ({count}/{self.max_buys})，停止买入")
            return

        self.logger.info(f"🚀 触发开多/加仓指令 (当前 {count} 次)")
        self._execute_open_order(side='buy', direction='LONG', price=price)

    def open_short(self, price):
        """
        [高层接口] 开空 / 加空
        """
        # 1. 风控检查
        allowed, count = self.can_buy()
        if not allowed:
            self.logger.info(f"🚫 达到最大持仓限制 ({count}/{self.max_buys})，停止卖出")
            return

        self.logger.info(f"📉 触发开空/加仓指令 (当前 {count} 次)")
        self._execute_open_order(side='sell', direction='SHORT', price=price)

    def close_position(self):
        """
        [高层接口] 平仓 (以交易所真实持仓为准)
        """
        self.logger.info("🔄 触发平仓指令，正在查询真实持仓...")
        try:
            # 1. 查询真实持仓
            positions = self.exchange.fetch_current_positions(self.symbol)
            
            target_pos = None
            for p in positions:
                if float(p['contracts']) > 0:
                    target_pos = p
                    break
            
            # 2. 数据一致性自愈
            if not target_pos:
                self.logger.warning("⚠️ 交易所无持仓，强制重置数据库状态")
                self.db.update_position(self.symbol, self.strategy_id, 'CLOSE', 0)
                return

            # 3. 确定平仓方向
            # 持有多单(long) -> 卖出平仓(sell)
            # 持有空单(short) -> 买入平仓(buy)
            amount_str = target_pos['contracts']
            side_to_close = 'sell' if target_pos['side'] == 'long' else 'buy'
            
            self.logger.info(f"执行平仓: {side_to_close} {amount_str} 张")

            # 4. 执行下单 (ReduceOnly)
            res = self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side=side_to_close,
                amount=float(amount_str),
                params={'reduceOnly': True}
            )

            # 5. 更新数据库 & 通知
            self.db.update_position(self.symbol, self.strategy_id, 'CLOSE', 0)
            self.db.log_order(self.strategy_id, self.symbol, side_to_close, 0, float(amount_str))
            
            Notifier.send_feishu(f"🏁 [{self.strategy_id}] 已平仓\n方向: {target_pos['side']}\n数量: {amount_str}")

        except Exception as e:
            msg = f"❌ 平仓失败: {e}"
            self.logger.error(msg)
            Notifier.send_feishu(msg, is_error=True)

    # ==========================================
    # 3. 底层原子操作 (Atomic Execution)
    # ==========================================

    def _execute_open_order(self, side, direction, price):
        """
        [原子操作] 开仓流程：计算 -> 下单 -> 记账 -> 通知
        """
        try:
            # 1. 动态计算数量
            amount = self.calculate_quantity(price)
            if not amount: return # 资金不足或计算失败

            # 2. 下单 (Market Order)
            res = self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side=side,
                amount=amount
            )
            
            # 获取实际成交均价(如果有)，否则用 ticker 价格
            avg_price = res.get('average') or price

            # 3. 更新数据库
            self.db.update_position(self.symbol, self.strategy_id, 'OPEN', avg_price, direction=direction)
            self.db.log_order(self.strategy_id, self.symbol, side, avg_price, amount)

            # 4. 发送通知
            emoji = "🚀" if direction == 'LONG' else "📉"
            msg = f"{emoji} [{self.strategy_id}] 开仓成功\n方向: {direction}\n数量: {amount}\n均价: {avg_price}"
            Notifier.send_feishu(msg)

        except Exception as e:
            msg = f"❌ 下单异常: {e}"
            self.logger.error(msg)
            Notifier.send_feishu(msg, is_error=True)