import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import os
import sys

# 将项目根目录加入路径，确保能导入 src 和 backtest 模块
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtest.runner import BacktestRunner

# ===================================
# 页面配置
# ===================================
st.set_page_config(
    page_title="OKX 量化回测面板",
    page_icon="📈",
    layout="wide"
)

# ===================================
# 辅助函数
# ===================================
def get_csv_files():
    """获取 data/history 下的所有 CSV 文件"""
    directory = "data/history"
    if not os.path.exists(directory):
        os.makedirs(directory)
    files = [f for f in os.listdir(directory) if f.endswith(".csv")]
    return files

def calculate_trade_metrics(orders):
    """
    根据订单记录粗略计算胜率
    注意：这是一个估算，因为MockExchange主要记录了余额变动
    更精确的胜率需要将 开仓单 和 平仓单 一一对应
    """
    if not orders:
        return 0, 0, 0
    
    # 简单统计：只要是平仓操作(reduceOnly logic 或 实际平仓)，且余额增加，算赢
    # 这里我们简化逻辑：统计所有订单，很难在不改变底层的情况下精确算出每一笔的胜率
    # 所以这里暂时只返回交易次数，后续可优化
    total_trades = len(orders)
    return total_trades

# ===================================
# 侧边栏配置
# ===================================
st.sidebar.header("⚙️ 回测参数设置")

# 1. 文件选择
csv_files = get_csv_files()
selected_file = st.sidebar.selectbox("选择历史数据 (CSV)", csv_files)

# 2. 资金设置
initial_balance = st.sidebar.number_input("初始资金 (USDT)", value=10000.0, step=1000.0)
leverage = st.sidebar.slider("杠杆倍数", 1, 10, 3)

# 3. 仓位管理
size_mode = st.sidebar.selectbox("仓位模式", ["PERCENT_BALANCE", "FIXED_MARGIN"])
size_value = 0.0
if size_mode == "PERCENT_BALANCE":
    size_value = st.sidebar.slider("投入余额百分比", 0.05, 1.0, 0.5, 0.05)
else:
    size_value = st.sidebar.number_input("固定保证金 (U)", value=100.0, step=10.0)

# 4. 策略参数 (这里以双均线为例，可扩展)
st.sidebar.subheader("策略参数 (双均线)")
ma_short = st.sidebar.number_input("短周期 MA", value=21)
ma_long = st.sidebar.number_input("长周期 MA", value=55)

btn_start = st.sidebar.button("🚀 开始回测", type="primary")

# ===================================
# 主逻辑
# ===================================
st.title("📊 OKX 量化策略回测面板")

if btn_start:
    if not selected_file:
        st.error("请先在 data/history 目录下准备数据文件！")
    else:
        # 1. 构造配置
        file_path = f"data/history/{selected_file}"
        symbol_guess = selected_file.split('_')[0] + '/' + selected_file.split('_')[1] + ':' + selected_file.split('_')[2]
        
        strat_conf = {
            'id': 'BT_APP_RUN',
            'strategy': 'DOUBLE_MA',
            'symbol': symbol_guess,
            'timeframe': selected_file.split('_')[-1].replace('.csv', ''),
            'leverage': leverage,
            'size_mode': size_mode,
            'size_value': size_value,
            'max_buys': 1
            # 注意：目前的 DoubleMAStrategy 写死了 21/55，
            # 如果要动态传参 ma_short，需要修改 DoubleMAStrategy 的 __init__ 和 run
            # 这里暂时展示标准逻辑
        }

        # 2. 运行回测
        with st.spinner('正在回测中，请稍候...'):
            try:
                runner = BacktestRunner(file_path, strat_conf, initial_balance=initial_balance)
                df_res, stats = runner.run()
                
                # 3. 展示指标卡片
                st.subheader("1. 核心绩效")
                col1, col2, col3, col4 = st.columns(4)
                
                col1.metric("总收益率", stats.get('Total Return', '0%'))
                col2.metric("最终净值", f"{stats.get('Final Balance', 0):.2f} U")
                col3.metric("最大回撤", stats.get('Max Drawdown', '0%'))
                col4.metric("夏普比率", stats.get('Sharpe Ratio', '0'))

                # 4. 绘制资金曲线
                st.subheader("2. 账户净值曲线")
                fig_equity = px.line(df_res, x='date', y='equity', title='资金增长趋势')
                fig_equity.update_layout(height=400)
                st.plotly_chart(fig_equity, use_container_width=True)

                # 5. 绘制 K 线与买卖点
                st.subheader("3. 交易可视化")
                
                # 为了画图，重新计算一下指标 (因为 Runner 跑完只返回了资金曲线，没返回带指标的 DF)
                # 我们复用 runner.df (原始数据) 并手动算一下均线以便画图
                df_chart = runner.df.copy()
                df_chart['datetime'] = pd.to_datetime(df_chart['timestamp'], unit='ms')
                df_chart['ema_short'] = df_chart['close'].ewm(span=ma_short, adjust=False).mean()
                df_chart['ema_long'] = df_chart['close'].ewm(span=ma_long, adjust=False).mean()

                # 提取买卖点
                orders = runner.mock_ex.orders
                buy_orders = [o for o in orders if o['side'] == 'buy']
                sell_orders = [o for o in orders if o['side'] == 'sell']
                
                # K线图
                fig_candle = go.Figure(data=[go.Candlestick(
                    x=df_chart['datetime'],
                    open=df_chart['open'],
                    high=df_chart['high'],
                    low=df_chart['low'],
                    close=df_chart['close'],
                    name='K线'
                )])

                # 均线
                fig_candle.add_trace(go.Scatter(x=df_chart['datetime'], y=df_chart['ema_short'], line=dict(color='orange', width=1), name=f'EMA{ma_short}'))
                fig_candle.add_trace(go.Scatter(x=df_chart['datetime'], y=df_chart['ema_long'], line=dict(color='blue', width=1), name=f'EMA{ma_long}'))

                # 买单标记 (紫色向上三角)
                if buy_orders:
                    buy_df = pd.DataFrame(buy_orders)
                    # 将时间戳转为 datetime 以便对齐 X 轴
                    buy_df['dt'] = pd.to_datetime(buy_df['timestamp'], unit='ms')
                    fig_candle.add_trace(go.Scatter(
                        x=buy_df['dt'], y=buy_df['price'],
                        mode='markers', name='买入',
                        marker=dict(symbol='triangle-up', size=10, color='purple')
                    ))

                # 卖单标记 (红色向下三角)
                if sell_orders:
                    sell_df = pd.DataFrame(sell_orders)
                    sell_df['dt'] = pd.to_datetime(sell_df['timestamp'], unit='ms')
                    fig_candle.add_trace(go.Scatter(
                        x=sell_df['dt'], y=sell_df['price'],
                        mode='markers', name='卖出',
                        marker=dict(symbol='triangle-down', size=10, color='red')
                    ))

                fig_candle.update_layout(height=600, xaxis_rangeslider_visible=False, title="K线、均线与交易记录")
                st.plotly_chart(fig_candle, use_container_width=True)

                # 6. 交易日志表格
                st.subheader("4. 详细交易日志")
                if orders:
                    df_orders = pd.DataFrame(orders)
                    df_orders['time'] = pd.to_datetime(df_orders['timestamp'], unit='ms')
                    # 调整列顺序
                    cols = ['time', 'symbol', 'side', 'price', 'amount', 'fee', 'balance_snapshot']
                    st.dataframe(df_orders[cols], use_container_width=True)
                else:
                    st.info("本次回测未产生任何交易。")

            except Exception as e:
                st.error(f"回测发生错误: {e}")
                # 打印详细堆栈以便调试
                import traceback
                st.text(traceback.format_exc())

else:
    st.info("👈 请在左侧选择数据文件并点击【开始回测】")