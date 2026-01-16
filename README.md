# AIQuant_OKX - 加密货币量化交易与回测系统

这是一个基于 Python 和 OKX API 的加密货币量化交易机器人，包含实盘交易引擎和历史回测系统。

## 🚀 功能特性

*   **实盘/模拟盘交易**: 支持 OKX 交易所的现货和合约交易。
*   **策略框架**: 基于类的策略设计，易于扩展新策略（目前内置双均线策略）。
*   **回测系统**: 提供基于历史数据的回测引擎，支持资金曲线模拟。
*   **可视化面板**: 基于 Streamlit 的交互式回测控制台，支持参数调整和结果可视化。
*   **风险控制**: 支持仓位管理和杠杆设置。
*   **消息通知**: 集成钉钉/Telegram/飞书消息推送（需配置）。

## 📂 目录结构

```text
CryptoTrader/
├── .env                # [私密] 存放 API Key 和环境配置
├── config.py           # [配置] 全局配置加载
├── main.py             # [入口] 实盘/模拟盘主程序
├── requirements.txt    # [依赖] Python 依赖库列表
├── data/               # [数据] 存放数据库和历史数据
│   ├── trade.db        # SQLite 数据库 (记录持仓和订单)
│   └── history/        # 下载的历史 CSV 数据
├── logs/               # [日志] 运行日志
├── src/                # [源码] 核心交易逻辑
│   ├── exchange.py     # 交易所 API 封装 (CCXT)
│   ├── strategy.py     # (旧) 策略入口
│   ├── trader.py       # 交易执行器
│   ├── database.py     # 数据库操作
│   ├── notification.py # 消息推送
│   └── strategies/     # 策略模块
│       ├── base.py     # 策略基类
│       └── double_ma.py# 双均线策略实现
└── backtest/           # [回测] 回测模块
    ├── app.py          # Streamlit 可视化界面
    ├── runner.py       # 回测执行脚本
    ├── mock_exchange.py# 模拟交易所
    └── downloader.py   # 数据下载工具
```

## 🛠️ 安装与配置

### 1. 环境准备

确保已安装 Python 3.10+。

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境 (Windows)
.\.venv\Scripts\activate

# 激活虚拟环境 (Mac/Linux)
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置文件

复制 `.env.example` (如果不存在则手动创建) 为 `.env`，并填入您的 OKX API Key：

```ini
# .env 文件内容示例

# 交易模式: DEMO (模拟盘) / REAL (实盘)
TRADING_MODE=DEMO

# OKX 模拟盘 API
OKX_DEMO_API_KEY=your_demo_api_key
OKX_DEMO_SECRET=your_demo_secret
OKX_DEMO_PASSPHRASE=your_demo_passphrase

# OKX 实盘 API (谨慎填写)
OKX_REAL_API_KEY=your_real_api_key
OKX_REAL_SECRET=your_real_secret
OKX_REAL_PASSPHRASE=your_real_passphrase

# 消息推送 (可选)
DINGTALK_TOKEN=
```

## ▶️ 运行指南

### 实盘/模拟盘交易

```bash
python main.py
```
程序将根据 `config.py` 和 `.env` 中的配置连接交易所并开始运行策略。

### 策略回测

**方式一：命令行运行**

```bash
python backtest/runner.py
```

**方式二：可视化界面 (推荐)**

```bash
# streamlit run backtest/app.py
$ & "c:\Users\ybai\Documents\trae_projects\AIQuant_OKX\.venv\Scripts\python.exe" -m streamlit run backtest/app.py
```
启动后在浏览器访问显示的 URL (通常是 `http://localhost:8501`) 即可使用图形界面进行回测。


## 📝 策略开发

1.  在 `src/strategies/` 目录下创建新的策略文件。
2.  继承 `src.strategies.base.BaseStrategy` 类。
3.  实现 `run()` 方法，编写您的交易逻辑。
4.  在 `config.py` 或回测界面中引用新策略。

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。数字货币交易风险极高，请谨慎使用实盘功能，作者不对任何资金损失负责。
