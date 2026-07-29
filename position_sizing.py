# -*- coding: utf-8 -*-
"""
第五层：动态仓位管理模型
总仓位跟随市场评分分档，单票仓位20~25%，同时持仓1~5只。
"""

import config


def allocate_positions(market_timing_result: dict, buy_signals: list, current_holding_count: int = 0) -> dict:
    """
    根据市场分档总仓位上限、当前已持仓数量，为新的买入信号分配仓位。
    返回：{ "total_position_cap": [min,max], "allocations": [{code, weight}, ...] , "notes": [...] }
    """
    pos_min, pos_max = market_timing_result["position_cap_range"]
    notes = []

    available_slots = max(0, config.MAX_CONCURRENT_HOLDINGS - current_holding_count)
    if available_slots == 0:
        notes.append("已达最大同时持仓数量上限（%d只），本轮不新增仓位" % config.MAX_CONCURRENT_HOLDINGS)
        return {"total_position_cap": [pos_min, pos_max], "allocations": [], "notes": notes}

    if pos_max == 0:
        notes.append("市场处于防守模式，强制空仓，不开新仓")
        return {"total_position_cap": [0, 0], "allocations": [], "notes": notes}

    # 按个股评分从高到低排序，优先分配额度更高的仓位（不超过单票上限）
    ranked = sorted(buy_signals, key=lambda x: x.get("stock_score", 0), reverse=True)[:available_slots]

    allocations = []
    for stock in ranked:
        # 评分越高，在单票 20%~25% 区间内取值越靠上限
        score_ratio = min(max((stock.get("stock_score", 85) - 85) / 15, 0), 1)  # 85~100 映射到 0~1
        weight = config.SINGLE_STOCK_POSITION_MIN + score_ratio * (
            config.SINGLE_STOCK_POSITION_MAX - config.SINGLE_STOCK_POSITION_MIN
        )
        allocations.append({"code": stock["code"], "weight": round(weight, 4)})

    total_new_weight = sum(a["weight"] for a in allocations)
    if total_new_weight > pos_max:
        notes.append("新增仓位总和 %.1f%% 超过本轮总仓位上限 %.1f%%，按比例缩减" % (total_new_weight * 100, pos_max * 100))
        scale = pos_max / total_new_weight if total_new_weight else 0
        for a in allocations:
            a["weight"] = round(a["weight"] * scale, 4)

    return {"total_position_cap": [pos_min, pos_max], "allocations": allocations, "notes": notes}
