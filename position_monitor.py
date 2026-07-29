# -*- coding: utf-8 -*-
"""
第六层：5分钟级持仓动态监控模块
读取网页录入的持仓（positions.json），逐一评估持有/加仓/减仓，输出 monitor.json。
"""

import logging
import sell_signal

logger = logging.getLogger("aiquant.position_monitor")


def classify_position(position: dict, market_score: float, sector_still_strong: bool = True) -> dict:
    """在卖出规则基础上，补充"加仓"判定：正向浮盈 + 趋势强化 + 放量。"""
    sell_eval = sell_signal.evaluate_position(position, market_score)
    action = sell_eval["action"]
    reasons = list(sell_eval["reasons"])

    if action == "持有" and sell_eval.get("pnl_ratio", 0) > 0.03 and sector_still_strong:
        action = "加仓"
        reasons.append("已产生正向浮盈，趋势持续强化，且所属板块依然强势，可小幅追加仓位")

    return {
        "code": position["code"],
        "cost_price": position.get("cost_price"),
        "quantity": position.get("quantity"),
        "last_price": sell_eval.get("last_price"),
        "pnl_ratio": sell_eval.get("pnl_ratio"),
        "action": action,
        "reasons": reasons,
    }


def monitor_all_positions(positions: list, market_score: float, top_sector_names: list = None) -> list:
    top_sector_names = top_sector_names or []
    results = []
    for position in positions:
        try:
            sector_still_strong = position.get("sector") in top_sector_names if position.get("sector") else True
            results.append(classify_position(position, market_score, sector_still_strong))
        except Exception as e:  # noqa: BLE001
            logger.warning("持仓监控失败 code=%s: %s", position.get("code"), e)
            results.append({"code": position.get("code"), "action": "持有", "reasons": [f"监控异常，需人工核查: {e}"]})
    return results
