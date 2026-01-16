import sqlite3
import os
import logging
from datetime import datetime

# 配置日志
logger = logging.getLogger('Database')

class DatabaseHandler:
    """
    数据库管理类 (合约版 - 支持多/空方向)
    """

    def __init__(self, db_path='data/trade.db'):
        """
        初始化数据库连接
        :param db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self):
        """确保 data 目录存在"""
        directory = os.path.dirname(self.db_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"📁 创建数据库目录: {directory}")

    def _get_conn(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        """
        初始化表结构 (升级：增加 direction 字段)
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # 1. 订单历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,         -- buy/sell
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    fee REAL
                )
            ''')

            # 2. 持仓状态表 (核心升级)
            # direction: 'LONG', 'SHORT', 'NONE'
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS state (
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    position_status INTEGER DEFAULT 0,  -- 0:空仓, 1:持仓
                    entry_price REAL DEFAULT 0.0,       -- 持仓均价
                    pos_count INTEGER DEFAULT 0,        -- 加仓次数
                    direction TEXT DEFAULT 'NONE',      -- 持仓方向
                    PRIMARY KEY (strategy_id, symbol)
                )
            ''')
            
            conn.commit()
            logger.info("✅ 数据库表结构加载完成 (支持多空双向)")
        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {e}")
        finally:
            conn.close()

    def get_position_details(self, symbol, strategy_id):
        """
        获取详细持仓状态
        :return: {'status': int, 'entry_price': float, 'pos_count': int, 'direction': str}
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT position_status, entry_price, pos_count, direction
                FROM state 
                WHERE strategy_id = ? AND symbol = ?
            ''', (strategy_id, symbol))
            
            row = cursor.fetchone()
            
            if row:
                return {
                    'status': row[0],
                    'entry_price': row[1],
                    'pos_count': row[2],
                    'direction': row[3] # 返回方向
                }
            else:
                return {
                    'status': 0, 
                    'entry_price': 0.0, 
                    'pos_count': 0, 
                    'direction': 'NONE'
                }
        except Exception as e:
            logger.error(f"❌ 查询持仓详情失败: {e}")
            return {'status': 0, 'entry_price': 0.0, 'pos_count': 0, 'direction': 'NONE'}
        finally:
            conn.close()

    def update_position(self, symbol, strategy_id, change_type, price, direction=None):
        """
        更新持仓状态
        :param change_type: 'OPEN' (开仓/加仓) | 'CLOSE' (平仓/清仓)
        :param price: 最新成交价/均价
        :param direction: 'LONG' | 'SHORT' (仅在 OPEN 时需要，CLOSE 时自动置为 NONE)
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        try:
            # 1. 获取旧状态
            current = self.get_position_details(symbol, strategy_id)
            new_count = current['pos_count']
            new_status = current['status']
            new_direction = current['direction']
            
            change_type = change_type.upper()

            # 2. 逻辑判断
            if change_type in ['OPEN', 'ADD', 'BUY']: # 兼容之前的 'BUY' 写法
                new_count += 1
                new_status = 1
                final_price = price
                
                # 如果传了方向，则更新方向；如果是加仓且未传方向，保持原方向
                if direction:
                    new_direction = direction
                elif new_direction == 'NONE' and direction is None:
                    # 这是一个异常情况：开仓却没指定方向
                    logger.warning(f"⚠️ 警告：开仓未指定方向，默认为 LONG")
                    new_direction = 'LONG'
                
            elif change_type in ['CLOSE', 'CLEAR', 'SELL_CLEAR']:
                new_count = 0
                new_status = 0
                final_price = 0.0
                new_direction = 'NONE' # 平仓后方向重置
            else:
                logger.warning(f"未知的更新类型: {change_type}")
                return

            # 3. 执行更新
            cursor.execute('''
                INSERT OR REPLACE INTO state (strategy_id, symbol, position_status, entry_price, pos_count, direction)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (strategy_id, symbol, new_status, final_price, new_count, new_direction))
            
            conn.commit()
            
            action_desc = f"{new_direction} 加仓({new_count})" if new_status == 1 else "平仓"
            logger.info(f"💾 状态更新 [{strategy_id}]: {action_desc} | 价格: {final_price}")

        except Exception as e:
            logger.error(f"❌ 更新状态失败: {e}")
            conn.rollback()
        finally:
            conn.close()

    def log_order(self, strategy_id, symbol, side, price, amount, fee=0):
        """
        记录成交订单
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                INSERT INTO orders (strategy_id, timestamp, symbol, side, price, amount, fee)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (strategy_id, timestamp, symbol, side, price, amount, fee))
            
            conn.commit()
            logger.info(f"📝 订单落库 [{strategy_id}]: {side} {symbol} @ {price}")
        except Exception as e:
            logger.error(f"❌ 记录订单失败: {e}")
        finally:
            conn.close()

# 测试代码
if __name__ == "__main__":
    # if os.path.exists('data/trade.db'):
    #    os.remove('data/trade.db')
       
    db = DatabaseHandler()
    sid = "BTC_TREND_01"
    sym = "BTC/USDT:USDT"
    
    print("--- 1. 开多单 (Open Long) ---")
    db.update_position(sym, sid, 'OPEN', 60000, direction='LONG')
    print(db.get_position_details(sym, sid))
    
    print("\n--- 2. 加仓多单 (Add Long) ---")
    # 加仓时方向可以传 LONG，也可以不传(自动沿用)
    db.update_position(sym, sid, 'OPEN', 59500) 
    print(db.get_position_details(sym, sid))
    
    print("\n--- 3. 平仓 (Close) ---")
    db.update_position(sym, sid, 'CLOSE', 61000)
    print(db.get_position_details(sym, sid))
    
    print("\n--- 4. 开空单 (Open Short) ---")
    db.update_position(sym, sid, 'OPEN', 62000, direction='SHORT')
    print(db.get_position_details(sym, sid))