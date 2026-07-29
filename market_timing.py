# -*- coding: utf-8 -*-
"""
第一层：市场环境择时模型
输出 0-100 的市场交易评分，并据此给出总仓位区间和模式名称。
"""

import logging
import pandas as pd

import config
import data_source as ds

logger = logging.getLogger("aiquant.market_timing")


def _trend_score_for_index(df: pd.DataFrame) -> float:
    """单个指数的均线趋势打分（0~1，之后乘以该指数在总分里的份额）。"""
    if df is None or df.empty or len(df) < 60:
        return 0.0
    last = df.iloc[-1]
    score = 0.0
    # 多头排列：MA5 > MA20 > MA60
    if last["ma5"] > last["ma20"] > last["ma60"]:
        score += 0.7
    elif last["ma5"] > last["ma20"]:
        score += 0.35
    # 有效跌破20日均线大幅扣分
    if last["close"] < last["ma20"] * 0.98:
        score -= 0.5
    return max(0.0, min(1.0, score + 0.3))  # 基础分0.3，避免恒为0


def index_trend_score() -> dict:
    """指数趋势（满分30）：上证/沪深300/创业板指 各占1/3份额。"""
    sub_scores = {}
    total = 0.0
    for name, symbol in config.INDEX_SYMBOLS.items():
        df = ds.get_index_daily(symbol)
        s = _trend_score_for_index(df)
        sub_scores[name] = round(s * config.INDEX_TREND_WEIGHT / 3, 2)
        total += sub_scores[name]
    return {"score": round(total, 2), "detail": sub_scores}


def profit_effect_score() -> dict:
    """市场赚钱效应（满分30）：涨停家数、跌停家数、上涨占比、最高连板高度。"""
    limit_up = ds.get_limit_up_pool()
    limit_down = ds.get_limit_down_pool()
    spot = ds.get_market_spot()

    up_count = len(limit_up) if not limit_up.empty else 0
    down_count = len(limit_down) if not limit_down.empty else 0

    max_board = 0
    if not limit_up.empty:
        board_col = next((c for c in ["连板数", "连板"] if c in limit_up.columns), None)
        if board_col:
            max_board = pd.to_numeric(limit_up[board_col], errors="coerce").max()
            max_board = 0 if pd.isna(max_board) else max_board

    up_ratio = 0.5
    if not spot.empty:
        chg_col = next((c for c in ["涨跌幅"] if c in spot.columns), None)
        if chg_col:
            chg = pd.to_numeric(spot[chg_col], errors="coerce")
            up_ratio = (chg > 0).sum() / max(len(chg), 1)

    # 简单线性加权，可按需再调
    score = 0.0
    score += min(up_count / 100, 1.0) * 10          # 涨停家数 -> 最多10分
    score += max(0.0, 1 - down_count / 50) * 8       # 跌停越少越好 -> 最多8分
    score += min(up_ratio * 2, 1.0) * 7              # 上涨占比 -> 最多7分
    score += min(max_board / 8, 1.0) * 5             # 连板高度 -> 最多5分

    return {
        "score": round(min(score, config.PROFIT_EFFECT_WEIGHT), 2),
        "detail": {"涨停家数": up_count, "跌停家数": down_count, "上涨占比": round(up_ratio, 3), "最高连板": max_board},
    }


def liquidity_score() -> dict:
    """市场流动性（满分20）：两市成交额及环比变化。"""
    spot = ds.get_market_spot()
    if spot.empty:
        return {"score": 0.0, "detail": {}}
    amount_col = next((c for c in ["成交额"] if c in spot.columns), None)
    if not amount_col:
        return {"score": 0.0, "detail": {}}
    total_amount = pd.to_numeric(spot[amount_col], errors="coerce").sum()
    # 没有历史成交额基线时，只能先用绝对水平粗略打分；建议后续接入历史成交额环比。
    # 经验阈值：两市合计 1.2万亿为中性，1.5万亿+为放量，8000亿以下为缩量（可在 config 里调整）。
    baseline = 1.2e12
    ratio = total_amount / baseline if baseline else 1.0
    score = min(max(ratio, 0.3), 1.5) / 1.5 * config.LIQUIDITY_WEIGHT
    return {"score": round(score, 2), "detail": {"两市成交额": total_amount, "相对基线倍数": round(ratio, 2)}}


def sentiment_score(sector_scores: list = None) -> dict:
    """市场情绪偏好（满分20）：主线持续性 + 龙头强度，用板块轮动结果做代理指标。"""
    if not sector_scores:
        # 情绪分需要板块轮动的结果作为输入；如果外部没传，退化为中性分。
        return {"score": config.SENTIMENT_WEIGHT * 0.5, "detail": {"说明": "未提供板块数据，使用中性分"}}
    top = sector_scores[0] if sector_scores else None
    leader_strength = top.get("leader_strength", 0.5) if top else 0.5
    persistence = top.get("persistence", 0.5) if top else 0.5
    score = (leader_strength * 0.6 + persistence * 0.4) * config.SENTIMENT_WEIGHT
    return {"score": round(score, 2), "detail": {"龙头强度": leader_strength, "主线持续性": persistence}}


def get_market_score(sector_scores: list = None) -> dict:
    """汇总四个子项，输出总分、分档仓位区间与模式。"""
    trend = index_trend_score()
    profit = profit_effect_score()
    liquidity = liquidity_score()
    sentiment = sentiment_score(sector_scores)

    total = trend["score"] + profit["score"] + liquidity["score"] + sentiment["score"]
    total = round(min(total, 100), 2)

    bracket = next(
        (b for b in config.MARKET_SCORE_BRACKETS if b[0] <= total < b[1] or (total == 100 and b[1] == 100)),
        config.MARKET_SCORE_BRACKETS[-1],
    )
    _, _, pos_min, pos_max, mode = bracket

    return {
        "total_score": total,
        "mode": mode,
        "position_cap_range": [pos_min, pos_max],
        "breakdown": {
            "指数趋势": trend,
            "赚钱效应": profit,
            "流动性": liquidity,
            "情绪偏好": sentiment,
        },
    }
