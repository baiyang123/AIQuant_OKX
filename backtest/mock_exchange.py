import time
import uuid
import logging

# 配置日志
logger = logging.getLogger('MockExchange')

class MockExchange:
    """
    模拟交易所 (用于回测)
    功能：
    1. 模拟账户余额和持仓状态
    2. 模拟订单撮合 (基于当前推送的 K 线价格)
    3. 模拟费率扣除 (万分之五)
    4. 模拟 PnL (盈亏) 结算
    """

    def __init__(self, initial_balance=10000.0):
        """
        :param initial_balance: 初始 USDT 资金
        """
        self.initial_balance = initial_balance
        self.balance = initial_balance  # 当前权益 (Equity)
        
        # 持仓状态: { 'BTC/USDT:USDT': {'side': 'long', 'contracts': 1.0, 'entry_price': 50000} }
        self.positions = {} 
        
        # 历史订单记录
        self.orders = []
        
        # 当前市场状态 (由回测引擎驱动更新)
        self.current_price = 0.0
        self.current_timestamp = 0
        
        # 费率配置
        self.fee_rate = 0.0005 # 0.05%

        # 模拟 CCXT 的 exchange 对象，用于应付 strategy 中直接调用 self.exchange.exchange 的情况
        self.exchange = self 

        # 2. 记录上一次扣除资金费的时间
        self.last_funding_time = 0

    # ============================================
    # 1. 状态更新接口 (由回测引擎调用)
    # ============================================
    def update_data(self, price, timestamp):
        """更新当前的市场环境"""
        self.current_price = price
        self.current_timestamp = timestamp

         # 模拟资金费逻辑：
        # 每过 8 小时 (28800000 毫秒) 结算一次
        # 假设费率为 0.01% (万分之一)，且大部分时间是 多头(我们) 支付给 空头
        # 这是一个保守的惩罚性设置，防止策略通过“死拿”来作弊
        
        if self.last_funding_time == 0:
            self.last_funding_time = timestamp
            
        # 如果时间间隔超过 8 小时
        if timestamp - self.last_funding_time >= 8 * 3600 * 1000:
            self._deduct_funding_fee()
            self.last_funding_time = timestamp

    def _deduct_funding_fee(self):
        """[模拟] 扣除资金费"""
        funding_rate = 0.0001 # 0.01%
        
        for symbol, pos in list(self.positions.items()):
            # 计算持仓名义价值
            position_value = pos['contracts'] * self.current_price
            
            # 计算费用
            fee = position_value * funding_rate
            
            # 只有多单扣钱 (保守模拟)，空单通常是收钱(回测中这里简化为不收不付或也扣钱以防万一)
            # 实战中：做多通常付钱，做空通常收钱
            if pos['side'] == 'long':
                self.balance -= fee
                # logger.info(f"[Funding] {symbol} 多单扣除资金费: {fee:.4f} U")

    # ============================================
    # 2. 模拟 Read 接口 (欺骗策略层)
    # ============================================
    def fetch_balance(self):
        """模拟返回账户余额结构"""
        return {
            'USDT': {
                'free': self.balance, # 简化：假设所有资金都可用 (暂不计算冻结保证金)
                'used': 0.0,
                'total': self.balance
            }
        }

    def get_available_balance(self, currency='USDT'):
        """获取可用余额"""
        return self.balance

    def get_current_price(self, symbol):
        """获取当前价格"""
        return self.current_price

    def fetch_current_positions(self, symbol):
        """
        获取持仓信息
        返回结构必须与实盘 CCXT 一致，否则策略层解析会报错
        """
        pos = self.positions.get(symbol)
        if not pos or pos['contracts'] <= 0:
            return []

        # 计算浮动盈亏 (Unrealized PnL)
        # 多单: (当前价 - 均价) * 数量
        # 空单: (均价 - 当前价) * 数量
        if pos['side'] == 'long':
            pnl = (self.current_price - pos['entry_price']) * pos['contracts']
        else:
            pnl = (pos['entry_price'] - self.current_price) * pos['contracts']

        # 构造返回字典
        return [{
            'symbol': symbol,
            'side': pos['side'],
            'contracts': str(pos['contracts']), # 实盘返回的是字符串
            'entryPrice': str(pos['entry_price']),
            'unrealizedPnl': str(pnl),
            'info': {'pos': str(pos['contracts'])} # 兼容性字段
        }]

    def amount_to_precision(self, symbol, amount):
        """
        模拟精度处理
        """
        # 简单保留 6 位小数，足以应付大部分回测
        return round(float(amount), 6)

    def set_leverage(self, leverage, symbol, params={}):
        """
        模拟设置杠杆 (回测中不做实际的保证金占用计算，仅打日志)
        """
        # logger.info(f"[Mock] 设置杠杆: {leverage}x ({symbol})")
        pass

    # ============================================
    # 3. 模拟 Write 接口 (撮合核心)
    # ============================================
    def create_order(self, symbol, type, side, amount, price=None, params={}):
        """
        模拟下单与撮合
        :param params: 支持 {'reduceOnly': True}
        """
        if self.current_price <= 0:
            raise Exception("MockExchange: 尚未初始化价格数据")

        price = self.current_price # 回测默认全部按当前 K 线收盘价成交 (市价单)
        value = price * amount
        fee = value * self.fee_rate
        
        # 扣除手续费
        self.balance -= fee
        
        # 核心：持仓变更逻辑
        is_reduce_only = params.get('reduceOnly', False)
        current_pos = self.positions.get(symbol)
        
        # --- 场景 1: 没有任何持仓 -> 开新仓 ---
        if not current_pos:
            if is_reduce_only:
                logger.warning("[Mock] 试图对空仓位进行 ReduceOnly 操作，忽略")
                return self._make_order_response(symbol, side, 0, price)
            
            # 记录方向：买入=做多，卖出=做空
            pos_side = 'long' if side == 'buy' else 'short'
            self.positions[symbol] = {
                'side': pos_side,
                'contracts': amount,
                'entry_price': price
            }
            
        # --- 场景 2: 已有持仓 ---
        else:
            # 判断是加仓还是平仓
            # 多单买入=加仓，多单卖出=平仓
            # 空单卖出=加仓，空单买入=平仓
            is_same_side = (current_pos['side'] == 'long' and side == 'buy') or \
                           (current_pos['side'] == 'short' and side == 'sell')
            
            if is_same_side:
                # --- 加仓 ---
                # 重新计算加权均价
                # (旧量*旧价 + 新量*新价) / 总量
                old_contracts = current_pos['contracts']
                old_price = current_pos['entry_price']
                
                new_total = old_contracts + amount
                new_avg_price = (old_contracts * old_price + amount * price) / new_total
                
                self.positions[symbol]['contracts'] = new_total
                self.positions[symbol]['entry_price'] = new_avg_price
                
            else:
                # --- 平仓/减仓 ---
                # 结算盈亏 (PnL)
                close_amount = min(amount, current_pos['contracts']) # 防止超额平仓
                
                if current_pos['side'] == 'long':
                    # 平多: (卖出价 - 入场价) * 数量
                    pnl = (price - current_pos['entry_price']) * close_amount
                else:
                    # 平空: (入场价 - 买入价) * 数量
                    pnl = (current_pos['entry_price'] - price) * close_amount
                
                # 盈亏入账
                self.balance += pnl
                
                # 更新持仓数量
                self.positions[symbol]['contracts'] -= close_amount
                
                # 如果平光了，删除持仓记录
                if self.positions[symbol]['contracts'] <= 0.0000001:
                    del self.positions[symbol]

        # 记录订单历史
        order_record = {
            'id': str(uuid.uuid4()),
            'timestamp': self.current_timestamp,
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'fee': fee,
            'balance_snapshot': self.balance # 记录该笔交易后的余额快照
        }
        self.orders.append(order_record)
        
        # logger.info(f"[MockOrder] {side} {amount} @ {price:.2f} | Fee: {fee:.4f} | Bal: {self.balance:.2f}")

        return self._make_order_response(symbol, side, amount, price)

    def _make_order_response(self, symbol, side, amount, price):
        """构造符合 CCXT 格式的返回结果"""
        return {
            'id': str(uuid.uuid4()),
            'info': {},
            'symbol': symbol,
            'type': 'market',
            'side': side,
            'status': 'filled', # 回测假设必定成交
            'price': price,
            'amount': amount,
            'filled': amount,
            'remaining': 0.0,
            'cost': price * amount,
            'average': price,
            'fee': {'cost': price * amount * self.fee_rate, 'currency': 'USDT'}
        }