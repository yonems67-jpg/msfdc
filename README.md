# AI量化交易决策终端 — 部署与验证说明

这套代码按你给的完整方案文档实现了七层框架的骨架和核心逻辑。请在正式接入实盘前，
先完整过一遍下面的"验证清单"——这不是客套话，是因为开发这套代码的沙箱环境
**没有访问 AKShare 底层数据源（东方财富/新浪财经等）的网络权限**，所以所有 AKShare
调用都只写完了代码、没能实机跑通。上传到阿里云之后，你需要自己跑一轮实测。

## 目录结构

```
aiquant/
  config.py            全部权重/阈值集中配置
  data_source.py        AKShare 数据获取封装（唯一需要重点验证的文件）
  market_timing.py      第一层：市场择时评分
  sector_rotation.py    第二层：板块轮动
  stock_scoring.py      第三层：多因子选股
  buy_signal.py          第四层：买入信号三重门槛
  position_sizing.py    第五层：动态仓位管理
  position_monitor.py   第六层：持仓监控
  sell_signal.py          第七层：分层卖出
  risk_control.py         第九节：硬性风控
  backtest.py             第十节：回测指标计算
  github_sync.py          GitHub Contents API 读写
  main_handler.py         阿里云 FC 定时函数入口
  position_api.py         阿里云 FC HTTP函数入口（持仓录入接口）
  requirements.txt
web/
  index.html    市场总览仪表盘（板块热力/选股池/信号/持仓监控/风险预警/回测曲线）
  positions.html 持仓录入与管理页面
  style.css / app.js
```

## 部署步骤

### 1. 定时选股/监控函数（main_handler.py）
1. 阿里云函数计算控制台 → 新建服务 → 新建函数 → 选择"事件函数"，运行时 Python 3.10。
2. 把 `aiquant/` 整个目录（除 `web/`）打包上传，或用 `fun`/`s` 工具部署；依赖必须在
   `requirements.txt` 基础上打进部署包里（不要指望函数运行时临时 pip install，那样不持久）。
3. 入口填 `main_handler.handler`。
4. 配置时间触发器，例如 `0 */5 9-15 * * 1-5`（注意阿里云时间触发器默认是 UTC，
   需要按 `+8` 换算成北京时间的交易时段）。
5. 环境变量：`GITHUB_TOKEN`、`GITHUB_REPO`（形如 `yourname/yourrepo`）、`GITHUB_BRANCH`（默认 main）。

### 2. 持仓录入接口（position_api.py）
1. 新建另一个函数，类型选"HTTP函数"，入口 `position_api.handler`。
2. 绑定 HTTP 触发器，拿到公网 URL。
3. 环境变量额外加一个 `API_SECRET`（自己起一串随机字符串）。
4. 把 `web/positions.html` 里的 `API_BASE_URL` 和 `API_SECRET` 换成你实际的值。

### 3. 前端（Cloudflare Pages）
把 `web/` 目录下的文件放进你现有仓库里 Cloudflare Pages 的构建输出目录下
（结合 `config.py` 里 `DATA_DIR_IN_REPO = "site/data"`，建议整个前端也放在 `site/` 下，
即 `site/index.html`、`site/positions.html`、`site/data/*.json`），沿用你原来的 Pages 自动部署。

## 验证清单（务必做完再接实盘）

在阿里云函数的在线终端或本地虚拟环境里，逐个跑通：

```python
import data_source as ds
print(ds.get_index_daily("sh000001").tail())        # 指数日线
print(ds.get_limit_up_pool().head())                  # 涨停池
print(ds.get_market_spot().head())                    # 全市场快照
print(ds.get_industry_board_list().head())            # 行业板块列表
print(ds.get_industry_fund_flow_rank().head())         # 行业资金流
print(ds.get_industry_hist("你的一个板块名").tail())
print(ds.get_industry_constituents("你的一个板块名").head())
print(ds.get_stock_fund_flow("600519").tail())
print(ds.get_stock_daily("600519").tail())
```

如果哪个函数报错或者拿到的 DataFrame 列名对不上（`data_source.py` 里我按常见列名写的，
比如 `"代码"`、`"涨跌幅"`、`"净额"`），照着报错信息把对应的 AKShare 函数名/列名改掉即可，
其余各层的业务逻辑不需要跟着动。

## 几个明确的简化/待你决策的地方（没有回避，直接列出来）

1. **市场情绪偏好分**：文档里说的"主线热点持续性、板块龙头走势、资金风险偏好"没有单一
   现成接口，`market_timing.sentiment_score()` 用的是板块轮动结果里龙头强度和持续性做代理，
   属于合理近似，但不是文档字面定义的独立数据源，如果你有更好的数据源建议替换。
2. **流动性打分的基线**：`liquidity_score()` 里用了一个写死的"两市成交额1.2万亿=中性"的经验
   基线，因为没有稳定的历史成交额环比数据接口。建议后续把每日成交额存进 `account_state.json`
   或单独的 `turnover_history.json`，改成真正的环比计算。
3. **MACD死叉**：`sell_signal._technical_breakdown()` 里的 MACD 判断是占位（恒为 False），
   因为严谨的 MACD 需要 EMA12/26/DIF/DEA 的完整计算，我没有把这部分单独实现进
   `data_source.py`（这个可以做，但涉及你要的历史数据长度和精度，建议你确认后我再补）。
4. **回测模块**：`backtest.compute_metrics()` 是完整可用的（只要你有交易记录）；
   但"每天重跑七层逻辑"的完整历史回放（`walk_forward_backtest`）只给了骨架，
   原因见 `backtest.py` 顶部注释——全历史逐日调用 AKShare 很容易被限流/超时，
   建议先用实盘运行自然积累 `trade_log.json`，或者分月跑短窗口回测。
5. **账户净值/总资金**：`account_state.json` 需要你手动维护 `total_capital`（总资金）和
   每日/每周起始净值，代码目前没有自动对接你的券商账户（文档里也没提到接券商接口，
   所以这部分没有做假设性实现）。

## 建议的 GitHub 仓库 json 文件（阿里云函数写入，前端读取）

```
site/data/market_score.json     市场择时评分
site/data/sector_rank.json      板块轮动TOP5
site/data/stock_pool.json        多因子选股池
site/data/signals.json           买入信号
site/data/monitor.json           持仓监控结果
site/data/risk_status.json        风控状态
site/data/positions.json          手动录入的持仓（由 position_api.py 读写）
site/data/account_state.json      账户净值/风控基线（需你手动维护或补充自动计算）
site/data/trade_log.json          历史成交记录（供回测用，需要你在实盘平仓时追加）
site/data/backtest_stats.json     回测统计结果（由你手动或另开一个函数调用 backtest.compute_metrics 生成）
site/data/last_run.json            最近一次运行时间戳
```

`stock_pool.json` 每轮都会写入（包括风控暂停新开仓时会写成空数组），前端"多因子选股池"
面板始终反映最新一轮的结果。
