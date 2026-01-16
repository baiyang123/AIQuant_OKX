from config import Config
from .double_ma import DoubleMAStrategy

# 策略注册表
# 如果你写了新策略，记得在这里导入并添加到字典里
STRATEGY_MAP = {
    'DOUBLE_MA': DoubleMAStrategy,
    # 'RSI': RsiStrategy, 
    # 'GRID': GridStrategy,
}

def load_strategies(exchange_client, db_handler):
    """
    根据 Config 配置，实例化所有策略对象
    :param exchange_client: 交易所实例
    :param db_handler: 数据库实例
    :return: 策略对象列表 List[BaseStrategy]
    """
    strategies = []
    
    if not hasattr(Config, 'ACTIVE_STRATEGIES'):
        print("⚠️ 未在 config.py 中找到 ACTIVE_STRATEGIES 配置")
        return []

    for strat_conf in Config.ACTIVE_STRATEGIES:
        # 1. 获取策略名称 (如 'DOUBLE_MA')
        strat_name = strat_conf.get('strategy')
        
        # 2. 在注册表中查找对应的类
        strategy_cls = STRATEGY_MAP.get(strat_name)
        
        if strategy_cls:
            try:
                # 3. 实例化 (传入依赖组件和专属配置)
                # 注意：这里必须与 BaseStrategy.__init__ 的参数对应
                instance = strategy_cls(exchange_client, db_handler, strat_conf)
                strategies.append(instance)
                print(f"✅ 策略加载成功: {strat_conf['id']} ({strat_name})")
            except Exception as e:
                print(f"❌ 策略 {strat_conf['id']} 初始化失败: {e}")
        else:
            print(f"⚠️ 跳过未知策略类型: {strat_name} (ID: {strat_conf.get('id')})")
            
    return strategies