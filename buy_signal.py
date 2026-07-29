# -*- coding: utf-8 -*-
"""
第四层：标准化买入模型
三重门槛：市场评分达标 + 个股综合评分达标 + 出现三类标准形态之一。
"""

import logging
import pandas as pd

import config
import data_source as ds

logger = logging.getLogger("aiquant.buy_signal")


def _detect_breakout(daily: pd.DataFrame) -> bool:
    """突破买入：突破关键压力位（近20日高点）且放量。"""
    if daily.empty or len(daily) < 20 or "volume" not in daily.columns:
        return False
    last = daily.iloc[-1]
    high_20_prev = daily["close"].iloc[:-1].tail(20).max()
    vol_ratio = last["volume"] / max(daily["volume"].tail(10).mean(), 1)
    return bool(last["close"] > high_20_prev and vol_ratio > 1.3)


def _detect_pullback_buy(daily: pd.DataFrame) -> bool:
    """回踩低吸买入：前期趋势完好，回踩MA5/MA10缩量企稳。"""
    if daily.empty or len(daily) < 20 or "volume" not in daily.columns:
        return False
    last = daily.iloc[-1]
    trend_ok = last["ma5"] > last["ma20"]
    near_ma = abs(last["close"] - last["ma10"]) / last["ma10"] < 0.02
    vol_shrink = last["volume"] < daily["volume"].tail(5).mean() * 0.8
    stabilized = last["close"] >= daily["close"].iloc[-2]
    return bool(trend_ok and near_ma and vol_shrink and stabilized)


def _detect_leader_rebound(daily: pd.DataFrame) -> bool:
    """龙头反包买入：短期恐慌回调后龙头快速修复走强。"""
    if daily.empty or len(daily) < 6:
        return False
    recent = daily.tail(5)
    had_drop = (recent["close"].iloc[0] / daily["close"].iloc[-6] - 1) < -0.05 if len(daily) >= 6 else False
    recovering = recent["close"].iloc[-1] > recent["close"].iloc[-2] > recent["close"].iloc[-3]
    return bool(had_drop and recovering)


def detect_pattern(code: str) -> dict:
    daily = ds.get_stock_daily(code)
    patterns = {
        "突破买入": _detect_breakout(daily),
        "回踩低吸买入": _detect_pullback_buy(daily),
        "龙头反包买入": _detect_leader_rebound(daily),
    }
    matched = [k for k, v in patterns.items() if v]
    return {"matched_any": len(matched) > 0, "patterns": patterns, "matched_patterns": matched}


def generate_buy_signals(market_score: float, stock_pool: list) -> list:
    """
    对第三层选出的股票池逐一核验三重门槛，输出可执行买入信号列表。
    stock_pool 里每个元素需要含 code / score / sector 字段（见 stock_scoring.get_stock_pool）。
    """
    if market_score < config.BUY_MARKET_SCORE_MIN:
        logger.info("市场评分 %.2f 未达到买入门槛 %.2f，本轮不生成任何买入信号", market_score, config.BUY_MARKET_SCORE_MIN)
        return []

    signals = []
    for stock in stock_pool:
        if stock["score"] < config.BUY_STOCK_SCORE_MIN:
            continue
        pattern_result = detect_pattern(stock["code"])
        if not pattern_result["matched_any"]:
            continue
        signals.append({
            "code": stock["code"],
            "sector": stock.get("sector"),
            "stock_score": stock["score"],
            "matched_patterns": pattern_result["matched_patterns"],
            "signal": "买入",
        })
    return signals
