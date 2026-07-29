# -*- coding: utf-8 -*-
"""
第九节：硬性全局风险控制规则（不可突破）
需要一个持久化的 account_state.json 来追踪当日/当周的账户净值基线，
因此这里的函数都要求调用方把 account_state 传进来、并把更新后的结果写回 GitHub。
account_state 结构建议：
{
  "day_start_equity": float,
  "week_start_equity": float,
  "current_date": "2026-07-29",
  "current_week": "2026-W31",
  "halt_new_positions_today": bool,
  "next_week_position_cap_override": float | null
}
"""

import config


def check_single_stock_hard_stoploss(position: dict, total_capital: float) -> dict:
    """单笔个股硬止损：亏损金额达到账户总资金2%，禁止加仓，择机离场。"""
    cost = position.get("cost_price", 0)
    last_price = position.get("last_price", cost)
    quantity = position.get("quantity", 0)
    if not cost or not total_capital:
        return {"triggered": False}

    loss_amount = max(0.0, (cost - last_price)) * quantity
    loss_ratio_of_capital = loss_amount / total_capital

    triggered = loss_ratio_of_capital >= config.SINGLE_STOCK_HARD_STOPLOSS_OF_TOTAL_CAPITAL
    return {
        "triggered": triggered,
        "loss_ratio_of_total_capital": round(loss_ratio_of_capital, 4),
        "action": "禁止加仓，择机离场" if triggered else None,
    }


def check_daily_drawdown(current_equity: float, account_state: dict) -> dict:
    """单日账户风控：当日整体回撤超过4%，当日停止所有新开仓操作。"""
    day_start = account_state.get("day_start_equity")
    if not day_start:
        return {"triggered": False, "drawdown": 0.0}
    drawdown = 1 - current_equity / day_start
    triggered = drawdown >= config.DAILY_DRAWDOWN_HALT_NEW_POSITIONS
    return {"triggered": triggered, "drawdown": round(drawdown, 4)}


def check_weekly_drawdown(current_equity: float, account_state: dict) -> dict:
    """单周账户风控：单周总回撤超过6%，次周仓位上限降至30%以内。"""
    week_start = account_state.get("week_start_equity")
    if not week_start:
        return {"triggered": False, "drawdown": 0.0}
    drawdown = 1 - current_equity / week_start
    triggered = drawdown >= config.WEEKLY_DRAWDOWN_SCALE_DOWN
    return {
        "triggered": triggered,
        "drawdown": round(drawdown, 4),
        "next_week_position_cap": config.WEEKLY_DRAWDOWN_NEXT_WEEK_CAP if triggered else None,
    }


def apply_risk_control(positions: list, current_equity: float, total_capital: float, account_state: dict) -> dict:
    """
    汇总所有硬性风控检查，返回：
    - halt_new_positions: 今日是否禁止新开仓
    - position_cap_override: 如果触发周度风控，覆盖本周仓位上限
    - stock_alerts: 每只个股的硬止损警报
    - forbidden_behavior_reminders: 固定提醒（第九节第4条不可突破的行为）
    """
    daily_check = check_daily_drawdown(current_equity, account_state)
    weekly_check = check_weekly_drawdown(current_equity, account_state)

    stock_alerts = []
    for position in positions:
        alert = check_single_stock_hard_stoploss(position, total_capital)
        if alert["triggered"]:
            stock_alerts.append({"code": position["code"], **alert})

    return {
        "halt_new_positions": bool(daily_check["triggered"] or account_state.get("halt_new_positions_today")),
        "daily_drawdown_check": daily_check,
        "weekly_drawdown_check": weekly_check,
        "position_cap_override": weekly_check.get("next_week_position_cap"),
        "stock_hard_stoploss_alerts": stock_alerts,
        "forbidden_behavior_reminders": [
            "禁止对亏损持仓摊薄成本",
            "禁止弱市（防守模式）强行交易",
            "禁止在高位抱团股重仓博弈，规避踩踏跌停风险",
        ],
    }
