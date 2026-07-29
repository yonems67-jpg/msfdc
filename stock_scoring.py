# -*- coding: utf-8 -*-
"""
第三层：股票多因子评分模型
只在第二层选出的强势板块内选股，输出3~5只核心标的。
"""

import logging
import pandas as pd

import config
import data_source as ds

logger = logging.getLogger("aiquant.stock_scoring")


def _fund_factor_score(code: str) -> float:
    """资金因子（满分40）：主力资金连续净流入 + 放量。"""
    flow = ds.get_stock_fund_flow(code)
    if flow.empty:
        return config.STOCK_FUND_FACTOR_WEIGHT * 0.3  # 无数据给保守基础分

    net_col = next((c for c in ["主力净流入-净额", "净额"] if c in flow.columns), None)
    if not net_col:
        return config.STOCK_FUND_FACTOR_WEIGHT * 0.3

    recent = pd.to_numeric(flow[net_col], errors="coerce").tail(3)
    consecutive_inflow = (recent > 0).all() if len(recent) == 3 else False

    score_ratio = 0.4
    if consecutive_inflow:
        score_ratio = 0.9
    elif (recent > 0).sum() >= 2:
        score_ratio = 0.65

    return round(score_ratio * config.STOCK_FUND_FACTOR_WEIGHT, 2)


def _trend_factor_score(daily: pd.DataFrame) -> float:
    """趋势因子（满分30）：MA5>MA10>MA20 多头排列 + 突破20日高点，且涨幅不过度透支。"""
    if daily.empty or len(daily) < 20:
        return 0.0
    last = daily.iloc[-1]
    score_ratio = 0.0
    if last["ma5"] > last["ma10"] > last["ma20"]:
        score_ratio += 0.5
    high_20 = daily["close"].tail(20).max()
    if last["close"] >= high_20 * 0.99:
        score_ratio += 0.3
    change_20d = last["close"] / daily["close"].iloc[-20] - 1
    if change_20d > 0.5:  # 20日涨幅超50%，视为高位透支，扣减
        score_ratio -= 0.2
    else:
        score_ratio += 0.2
    return round(max(0.0, min(score_ratio, 1.0)) * config.STOCK_TREND_FACTOR_WEIGHT, 2)


def _hotspot_factor_score(is_leader: bool) -> float:
    """热点因子（满分20）：是否所属主线板块龙头/人气标的。"""
    return config.STOCK_HOTSPOT_FACTOR_WEIGHT * (0.9 if is_leader else 0.5)


def _risk_penalty(daily: pd.DataFrame) -> float:
    """风险扣分项（最高扣10分）：短期高位爆炒 / 放量长阴出货等代理判断。"""
    if daily.empty or len(daily) < 10:
        return 0.0
    penalty = 0.0
    last = daily.iloc[-1]
    prev = daily.iloc[-2]
    # 放量长阴：收盘大跌且量能显著放大
    if "volume" in daily.columns:
        vol_ratio = last["volume"] / max(daily["volume"].tail(10).mean(), 1)
        pct_chg = last["close"] / prev["close"] - 1
        if pct_chg < -0.05 and vol_ratio > 1.5:
            penalty += 5
    # 短期高位爆炒：10日涨幅过大
    change_10d = last["close"] / daily["close"].iloc[-10] - 1
    if change_10d > 0.8:
        penalty += 5
    return min(penalty, config.STOCK_RISK_PENALTY_MAX)


def score_stock(code: str, is_leader: bool = False) -> dict:
    daily = ds.get_stock_daily(code)
    fund = _fund_factor_score(code)
    trend = _trend_factor_score(daily)
    hotspot = _hotspot_factor_score(is_leader)
    penalty = _risk_penalty(daily)

    total = round(fund + trend + hotspot - penalty, 2)
    return {
        "code": code,
        "score": total,
        "detail": {"资金因子": fund, "趋势因子": trend, "热点因子": hotspot, "风险扣分": penalty},
    }


def get_stock_pool(top_sectors: list) -> list:
    """在给定的强势板块列表内选股，返回按分排序后的 3~5 只标的。"""
    candidates = []
    for sector in top_sectors:
        cons = ds.get_industry_constituents(sector["sector"])
        if cons.empty:
            continue
        code_col = next((c for c in ["代码"] if c in cons.columns), None)
        chg_col = next((c for c in ["涨跌幅"] if c in cons.columns), None)
        if not code_col:
            continue
        leader_code = None
        if chg_col:
            leader_code = cons.loc[pd.to_numeric(cons[chg_col], errors="coerce").idxmax(), code_col]
        # 每个板块最多取前10只成分股参与打分，避免全市场遍历导致函数超时
        for _, row in cons.head(10).iterrows():
            code = row[code_col]
            result = score_stock(code, is_leader=(code == leader_code))
            result["sector"] = sector["sector"]
            candidates.append(result)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[: config.STOCK_POOL_OUTPUT_MAX]
