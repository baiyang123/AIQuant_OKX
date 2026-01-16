import sys
import os

# 将项目根目录添加到 python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import logging
import time
from datetime import datetime
import matplotlib.pyplot as plt

# 引入核心组件
from backtest.mock_exchange import MockExchange
from src.strategies.double_ma import DoubleMAStrategy

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(message)s') # 回测日志简化格式
logger = logging.getLogger('Backtest')

class MockDatabase:
    """
    内存数据库 (用于回测，不读写本地文件)
    完全模拟 src/database.py 的接口
    """
    def __init__(self):
        # 存储结构: { (strategy_id, symbol): {'status': 0, 'pos_count': 0, ...} }
        self.state = {}
        self.orders = []

    def get_position_details(self, symbol, strategy_id):
        key = (strategy_id, symbol)
        return self.state.get(key, {
            'status': 0, 
            'entry_price': 0.0, 
            'pos_count': 0, 
            'direction': 'NONE'
        })

    def update_position(self, symbol, strategy_id, change_type, price, direction=None):
        key = (strategy_id, symbol)
        current = self.get_position_details(symbol, strategy_id)
        
        # 复用 database.py 的逻辑
        new_count = current['pos_count']
        new_status = current['status']
        new_direction = current['direction']
        
        ct = change_type.upper()
        if ct in ['OPEN', 'ADD', 'BUY']:
            new_count += 1
            new_status = 1
            if direction: new_direction = direction
            elif new_direction == 'NONE': new_direction = 'LONG'
            
        elif ct in ['CLOSE', 'CLEAR']:
            new_count = 0
            new_status = 0
            new_direction = 'NONE'
            
        self.state[key] = {
            'status': new_status,
            'entry_price': price,
            'pos_count': new_count,
            'direction': new_direction
        }

    def log_order(self, strategy_id, symbol, side, price, amount, fee=0):
        self.orders.append({
            'strategy_id': strategy_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'timestamp': datetime.now() # 回测时这里记录的是真实时间，不影响逻辑
        })


class BacktestRunner:
    """
    回测引擎
    职责：
    1. 加载历史数据
    2. 驱动 MockExchange 时间流逝
    3. 喂数据给 Strategy
    4. 统计收益
    """
    def __init__(self, csv_path, strategy_config, initial_balance=10000):
        self.csv_path = csv_path
        self.cfg = strategy_config
        self.initial_balance = initial_balance
        
        # 加载数据
        self.df = self._load_data()
        
        # 初始化组件
        self.mock_db = MockDatabase()
        self.mock_ex = MockExchange(initial_balance)
        
        # ⚠️ 关键：给 mock_exchange 注入“历史数据切片”能力
        # 这样策略调用 fetch_ohlcv 时，才能拿到当时的 K 线
        self.mock_ex.fetch_ohlcv = self._mock_fetch_ohlcv
        
        # 初始化策略 (依赖注入)
        # 注意：这里我们直接实例化策略类，并将 mock 对象传进去
        self.strategy = DoubleMAStrategy(
            exchange_client=self.mock_ex,
            db_handler=self.mock_db,
            config_dict=self.cfg
        )
        
        # 统计数据
        self.equity_curve = [] # 净值曲线

    def _load_data(self):
        """读取清洗 CSV"""
        logger.info(f"📂 加载数据: {self.csv_path}")
        df = pd.read_csv(self.csv_path)
        # 确保时间戳是 int 类型 (毫秒)
        df['timestamp'] = df['timestamp'].astype(int)
        df = df.sort_values('timestamp').reset_index(drop=True)
        return df

    def _mock_fetch_ohlcv(self, symbol, timeframe, limit=100):
        """
        [黑魔法] 动态拦截策略的数据请求
        根据 mock_ex 的当前时间戳，返回过去 limit 根 K 线
        """
        current_ts = self.mock_ex.current_timestamp
        
        # 找到当前时间在 DataFrame 中的索引
        # 这是一个简单的查找，实际大规模回测可以用 numpy searchsorted 优化
        if current_ts == 0: return []
        
        # 筛选出 <= 当前时间的数据
        mask = self.df['timestamp'] <= current_ts
        # 取最后 limit 条
        subset = self.df.loc[mask].tail(limit)
        
        # 转换为 list 格式 (timestamp, open, high, low, close, volume)
        return subset[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()

    def run(self):
        """执行回测主循环"""
        logger.info(f"🚀 开始回测: {self.cfg['strategy']} on {self.cfg['symbol']}")
        logger.info(f"   数据量: {len(self.df)} 条 K 线")
        
        start_time = time.time()
        
        # 预热期：例如 EMA55 至少需要 55 条数据，我们从第 60 条开始跑
        warmup_period = 60 
        
        for idx, row in self.df.iterrows():
            if idx < warmup_period:
                continue
                
            # 1. 更新“虚拟时间”和“最新价格”
            # 注意：MockExchange 这里拿到的 price 是这根 K 线的 close
            # 实战中这意味着我们以收盘价成交 (偏乐观，但对于趋势策略可接受)
            self.mock_ex.update_data(row['close'], row['timestamp'])
            
            # 2. 执行策略
            self.strategy.run()
            
            # 3. 每日结算 (记录净值)
            # 计算总资产 = 余额 + 持仓未实现盈亏
            total_equity = self.mock_ex.balance
            
            # 遍历所有持仓算 PnL
            positions = self.mock_ex.fetch_current_positions(self.cfg['symbol'])
            for pos in positions:
                total_equity += float(pos['unrealizedPnl'])
                
            self.equity_curve.append({
                'timestamp': row['timestamp'],
                'date': row['datetime'], # 假设 CSV 里有 datetime 列
                'equity': total_equity,
                'price': row['close']
            })
            
            # 简单的进度打印
            if idx % 1000 == 0:
                print(f"   进度: {idx}/{len(self.df)} | 净值: {total_equity:.2f}")

        elapsed = time.time() - start_time
        logger.info(f"🏁 回测结束，耗时 {elapsed:.2f} 秒")
        
        return self._calculate_statistics()

    def _calculate_statistics(self):
        """计算回测绩效指标"""
        df_res = pd.DataFrame(self.equity_curve)
        
        # 边界情况处理
        if df_res.empty: 
            return pd.DataFrame(), {}
        
        initial = self.initial_balance
        final = df_res['equity'].iloc[-1]
        
        # 1. 收益率
        total_return = (final - initial) / initial
        
        # 2. 最大回撤
        df_res['peak'] = df_res['equity'].cummax()
        df_res['drawdown'] = (df_res['equity'] - df_res['peak']) / df_res['peak']
        max_drawdown = df_res['drawdown'].min()
        
        # 3. 夏普比率
        df_res['pct_change'] = df_res['equity'].pct_change()
        annual_factor = 2190 # 针对 4h
        if df_res['pct_change'].std() != 0:
            sharpe = (df_res['pct_change'].mean() / df_res['pct_change'].std()) * np.sqrt(annual_factor)
        else:
            sharpe = 0
        
        stats = {
            'Initial Balance': initial,
            'Final Balance': final,
            'Total Return': f"{total_return*100:.2f}%",
            'Max Drawdown': f"{max_drawdown*100:.2f}%",
            'Sharpe Ratio': f"{sharpe:.2f}",
            'Total Trades': len(self.mock_ex.orders)
        }
        
        for k, v in stats.items():
            logger.info(f"📊 {k}: {v}")
            
        # [修改点] 同时返回 DataFrame 和 统计字典
        return df_res, stats

# ==========================================
# 入口测试
# ==========================================
# ==========================================
# 入口测试
# ==========================================
if __name__ == '__main__':
    # 1. 准备回测配置
    strat_conf = {
        'id': 'BT_TEST_01',
        'strategy': 'DOUBLE_MA',
        'symbol': 'BTC/USDT:USDT',
        'timeframe': '4h',
        'leverage': 3,
        'size_mode': 'PERCENT_BALANCE',
        'size_value': 0.5,
        'max_buys': 1
    }
    
    # 2. 指定数据文件
    csv_file = 'data/history/BTC_USDT_USDT_4h.csv'
    
    import os
    if not os.path.exists(csv_file):
        print(f"❌ 找不到数据文件: {csv_file}")
        exit()

    # 3. 运行回测
    runner = BacktestRunner(csv_file, strat_conf, initial_balance=10000)
    
    # 【关键修改点 1】这里接收元组，解包出两个变量
    df_result, stats = runner.run()
    
    # 4. 简单画图
    if not df_result.empty:
        plt.figure(figsize=(12, 6))
        
        ax1 = plt.gca()
        ax1.plot(df_result['date'], df_result['equity'], color='orange', label='Equity')
        ax1.set_ylabel('Equity (USDT)')
        ax1.legend(loc='upper left')
        
        ax2 = ax1.twinx()
        ax2.plot(df_result['date'], df_result['price'], color='skyblue', alpha=0.3, label='Price')
        ax2.set_ylabel('Price')
        
        # 【关键修改点 2】直接使用 stats 字典，不要再调用函数了
        plt.title(f"Backtest: {strat_conf['strategy']} - Total Return: {stats['Total Return']}")
        
        plt.show()