from .base import BaseStrategy
import time

class DoubleMAStrategy(BaseStrategy):
    """
    双均线策略 (大脑版 - Structure B)
    职责：只负责信号计算和决策流程，不处理具体的交易细节。
    """
    
    def run(self):
        # ==========================
        # 1. 市场感知 (Market Data)
        # ==========================
        df = self.get_ohlcv_df()
        if df is None or len(df) < 60:
            return

        # 计算指标
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

        # 提取关键数据 (倒数第2根，防抖动)
        curr_idx = -2
        prev_idx = -3
        
        curr_ema21 = df['ema21'].iloc[curr_idx]
        curr_ema55 = df['ema55'].iloc[curr_idx]
        prev_ema21 = df['ema21'].iloc[prev_idx]
        prev_ema55 = df['ema55'].iloc[prev_idx]
        
        current_price = df['close'].iloc[curr_idx]
        
        # ==========================
        # 2. 信号生成 (Signal Gen)
        # ==========================
        signal = 'HOLD'
        if prev_ema21 < prev_ema55 and curr_ema21 > curr_ema55:
            signal = 'GOLDEN_CROSS' # 金叉
        elif prev_ema21 > prev_ema55 and curr_ema21 < curr_ema55:
            signal = 'DEATH_CROSS'  # 死叉
            
        # 获取自我状态
        pos = self.get_position_details()
        direction = pos['direction'] # 'LONG', 'SHORT', 'NONE'
        status = pos['status']       # 0, 1
        
        self.logger.info(f"[{self.symbol}] 信号:{signal} | 持仓:{direction} | 价格:{current_price:.2f}")

        # ==========================
        # 3. 决策执行 (Decision Making)
        # ==========================
        
        # --- 场景 A: 金叉 (看涨) ---
        if signal == 'GOLDEN_CROSS':
            
            # 1. 持有空单 -> 反手 (平空开多)
            if status == 1 and direction == 'SHORT':
                self.logger.info("🔄 信号反转: 平空单 -> 开多单")
                self.close_position() 
                
                # 暂停 2 秒，等待资金释放和 Orderbook 匹配
                time.sleep(2) 
                
                self.open_long(current_price)

            # 2. 空仓 -> 开多
            elif status == 0:
                self.logger.info("🚀 趋势启动: 开多单")
                self.open_long(current_price)
                
            # 3. 持有多单 -> 加仓
            elif status == 1 and direction == 'LONG':
                # 注意：can_buy 的检查已经在 open_long 内部做了，这里可以直接调
                # 但为了日志清晰，我们也可以简单打个 log
                self.logger.info("➕ 趋势增强: 尝试加仓(多)")
                self.open_long(current_price)

        # --- 场景 B: 死叉 (看跌) ---
        elif signal == 'DEATH_CROSS':
            
            # 1. 持有多单 -> 反手 (平多开空)
            if status == 1 and direction == 'LONG':
                self.logger.info("🔄 信号反转: 平多单 -> 开空单")
                self.close_position()
                time.sleep(2)
                self.open_short(current_price)
                
            # 2. 空仓 -> 开空
            elif status == 0:
                self.logger.info("📉 趋势启动: 开空单")
                self.open_short(current_price)
                
            # 3. 持有空单 -> 加仓
            elif status == 1 and direction == 'SHORT':
                self.logger.info("➕ 趋势增强: 尝试加仓(空)")
                self.open_short(current_price)