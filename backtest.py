# -*- coding: utf-8 -*-
"""
第十节：策略回测与迭代优化模块

设计说明（请务必先读完再用）：
真正"每天重跑一遍七层完整流水线"的历史回测，对 AKShare 免费接口来说请求量极大，
很容易被限流/超时，而且阿里云函数默认执行时长上限（通常几分钟到十几分钟）也扛不住
跑几年的全市场历史。所以这里拆成两块：

1. `compute_metrics(trade_log)`：只要你有交易记录（每一笔的开仓价/平仓价/日期/仓位），
   就能算出年化收益率、最大回撤、胜率、盈亏比、夏普比率、最大连续亏损次数、单周收益分布。
   这部分是完整可用的，不依赖额外的网络请求。

2. `walk_forward_backtest(...)`：一个简化版的"逐日重放"骨架，按天调用同一套 market_timing /
   sector_rotation / stock_scoring / buy_signal 逻辑生成信号，再用次日开盘价模拟成交。
   建议先用较短的时间窗口（比如最近1个月）跑通逻辑，确认没有超时和限流问题后，
   再拉长到你需要的回测区间；必要时分批（按月）跑，把结果 append 到同一份 trade_log 里。

交易记录建议每次由"实盘运行"自动追加到 site/data/trade_log.json，
这样回测数据是从生产环境自然积累出来的，不需要每次都重新回放全历史。
"""

import logging
import math
from datetime import datetime

import pandas as pd

logger = logging.getLogger("aiquant.backtest")


def compute_metrics(trade_log: list, initial_capital: float) -> dict:
    """
    trade_log: [{"code":, "open_date":, "close_date":, "open_price":, "close_price":,
                 "quantity":, "position_weight":}, ...]
    """
    if not trade_log:
        return {"error": "trade_log 为空，暂无可统计的交易记录"}

    df = pd.DataFrame(trade_log)
    df["open_date"] = pd.to_datetime(df["open_date"])
    df["close_date"] = pd.to_datetime(df["close_date"])
    df["pnl_ratio"] = df["close_price"] / df["open_price"] - 1
    df["pnl_amount"] = df["pnl_ratio"] * df["quantity"] * df["open_price"]

    win_trades = df[df["pnl_amount"] > 0]
    lose_trades = df[df["pnl_amount"] <= 0]
    win_rate = len(win_trades) / len(df) if len(df) else 0.0

    avg_win = win_trades["pnl_amount"].mean() if not win_trades.empty else 0.0
    avg_loss = abs(lose_trades["pnl_amount"].mean()) if not lose_trades.empty else 0.0
    profit_loss_ratio = (avg_win / avg_loss) if avg_loss else float("inf")

    # 按平仓日期构建净值曲线（简化：假设交易之间资金滚动使用，逐笔累加盈亏到初始资金）
    df = df.sort_values("close_date")
    df["cum_pnl"] = df["pnl_amount"].cumsum()
    df["equity"] = initial_capital + df["cum_pnl"]

    running_max = df["equity"].cummax()
    drawdown = 1 - df["equity"] / running_max
    max_drawdown = drawdown.max() if not drawdown.empty else 0.0

    total_days = max((df["close_date"].max() - df["open_date"].min()).days, 1)
    total_return = df["equity"].iloc[-1] / initial_capital - 1
    annualized_return = (1 + total_return) ** (365 / total_days) - 1 if total_return > -1 else -1.0

    # 夏普比率：用逐笔收益率近似（非严格日频），无风险利率按0处理
    returns = df["pnl_ratio"]
    sharpe = (returns.mean() / returns.std() * math.sqrt(252)) if returns.std() else 0.0

    # 最大连续亏损次数
    is_loss = (df["pnl_amount"] <= 0).tolist()
    max_consecutive_losses, current = 0, 0
    for loss in is_loss:
        current = current + 1 if loss else 0
        max_consecutive_losses = max(max_consecutive_losses, current)

    # 单周收益分布
    df["week"] = df["close_date"].dt.strftime("%Y-W%V")
    weekly_pnl = df.groupby("week")["pnl_amount"].sum().to_dict()

    return {
        "annualized_return": round(annualized_return, 4),
        "max_drawdown": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 3) if profit_loss_ratio != float("inf") else None,
        "sharpe_ratio": round(sharpe, 3),
        "max_consecutive_losses": max_consecutive_losses,
        "weekly_pnl_distribution": weekly_pnl,
        "total_trades": len(df),
        "equity_curve": df[["close_date", "equity"]].assign(
            close_date=lambda x: x["close_date"].dt.strftime("%Y-%m-%d")
        ).to_dict("records"),
    }


def walk_forward_backtest(start_date: str, end_date: str, initial_capital: float) -> dict:
    """
    简化版逐日重放骨架。默认不在这里直接跑全市场（太慢/太容易限流），
    只演示单日一次完整流水线怎么串起来，方便你按需扩展成真正的逐日循环。
    """
    import market_timing
    import sector_rotation
    import stock_scoring
    import buy_signal

    logger.info("walk_forward_backtest 目前是骨架实现：%s ~ %s，仅演示单次流水线串联，不做逐日循环。", start_date, end_date)

    market_result = market_timing.get_market_score()
    top_sectors = sector_rotation.get_top_sectors()
    stock_pool = stock_scoring.get_stock_pool(top_sectors)
    signals = buy_signal.generate_buy_signals(market_result["total_score"], stock_pool)

    return {
        "note": "这是骨架示例，请参考本函数把 market/sector/stock/buy 四步骤放进真正的逐日 for 循环，"
                "并在每个交易日用当天的历史数据重新计算（需要你在 data_source.py 里补充按日期取历史快照的函数）。",
        "sample_market_score": market_result,
        "sample_top_sectors": [s["sector"] for s in top_sectors],
        "sample_signals": signals,
    }
