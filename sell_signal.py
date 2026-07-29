# -*- coding: utf-8 -*-
"""
第七层：分层卖出执行模型
动态阶梯止盈 + 技术形态卖出 + 资金面卖出 + 市场环境卖出。
"""

import logging
import config
import data_source as ds

logger = logging.getLogger("aiquant.sell_signal")


def _pnl_ratio(position: dict, last_price: float) -> float:
    cost = position.get("cost_price", 0)
    if not cost:
        return 0.0
    return last_price / cost - 1


def _technical_breakdown(daily) -> bool:
    if daily.empty or len(daily) < 12:
        return False
    last = daily.iloc[-1]
    prev = daily.iloc[-2]
    ma10_break = last["close"] < last["ma10"] and prev["close"] >= prev["ma10"]
    long_yin = (last["close"] / prev["close"] - 1) < -0.05 and "volume" in daily.columns and (
        last["volume"] > daily["volume"].tail(10).mean() * 1.4
    )
    # MACD 死叉的严谨计算需要 EMA12/26/DIF/DEA；这里给出可直接替换的占位判断，
    # 如需精确 MACD 请在 data_source 里补充计算后传入。
    macd_dead_cross_placeholder = False
    return bool(ma10_break or long_yin or macd_dead_cross_placeholder)


def evaluate_position(position: dict, market_score: float) -> dict:
    """
    对单个持仓（dict: code/cost_price/quantity/opened_at）评估应执行的卖出动作。
    返回 {"action": "持有"/"减仓50%"/"清仓", "reasons": [...]}
    """
    code = position["code"]
    daily = ds.get_stock_daily(code)
    if daily.empty:
        return {"action": "持有", "reasons": ["行情数据缺失，暂维持原状，建议人工核查"]}

    last_price = daily.iloc[-1]["close"]
    pnl = _pnl_ratio(position, last_price)
    reasons = []
    action = "持有"

    # 1. 市场环境卖出：优先级最高，评分跌破阈值直接全部清仓
    if market_score < config.MARKET_SCORE_FORCE_CLEAR:
        return {"action": "清仓", "reasons": [f"市场择时评分 {market_score:.1f} 跌破 {config.MARKET_SCORE_FORCE_CLEAR}，全部持仓强制清仓"], "pnl_ratio": round(pnl, 4)}

    # 2. 技术形态卖出
    if _technical_breakdown(daily):
        reasons.append("触发技术形态卖出：跌破MA10 / 放量长阴")
        action = "清仓"

    # 3. 资金面卖出：连续N日主力资金净流出
    flow = ds.get_stock_fund_flow(code)
    if not flow.empty:
        net_col = next((c for c in ["主力净流入-净额", "净额"] if c in flow.columns), None)
        if net_col:
            recent = flow[net_col].tail(config.FUND_OUTFLOW_SELL_DAYS)
            if len(recent) == config.FUND_OUTFLOW_SELL_DAYS and (recent < 0).all():
                reasons.append(f"连续{config.FUND_OUTFLOW_SELL_DAYS}日主力资金净流出，降低持仓仓位")
                action = "减仓50%" if action == "持有" else action

    # 4. 动态阶梯止盈（只有在没有更强的清仓信号时才按止盈规则处理）
    if action == "持有":
        if pnl >= config.TAKE_PROFIT_TIER_2:
            reasons.append(f"浮盈{pnl*100:.1f}%，超过{config.TAKE_PROFIT_TIER_2*100:.0f}%，保留底仓跟随趋势")
            action = "保留底仓"
        elif config.TAKE_PROFIT_TIER_1 <= pnl < config.TAKE_PROFIT_TIER_1_END:
            reasons.append(f"浮盈{pnl*100:.1f}%，达到止盈区间，减仓{config.TAKE_PROFIT_TIER_1_REDUCE_RATIO*100:.0f}%锁定利润")
            action = f"减仓{int(config.TAKE_PROFIT_TIER_1_REDUCE_RATIO*100)}%"

    if not reasons:
        reasons.append("趋势完好，主力资金无持续流出，维持原有仓位")

    return {"action": action, "reasons": reasons, "pnl_ratio": round(pnl, 4), "last_price": last_price}
