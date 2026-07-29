# -*- coding: utf-8 -*-
"""
阿里云函数计算（FC）入口 —— 定时触发器每5分钟调用一次。

部署时：
1. 在 FC 控制台新建"事件函数"，运行时选 Python 3.10（或你本地开发用的版本），
   入口填 `main_handler.handler`。
2. 配置一个"时间触发器"，cron 表达式建议：0 */5 9-15 * * 1-5（交易时段每5分钟，工作日）。
   注意阿里云 cron 是6位（含秒），且默认时区通常是 UTC，需要按你的地区做时区换算。
3. 环境变量里配置 GITHUB_TOKEN / GITHUB_REPO / GITHUB_BRANCH（见 github_sync.py 顶部注释）。
4. requirements.txt 里的依赖需要在"函数代码"里以层(Layer)或直接打包 site-packages 的方式带上，
   FC 的临时终端能装包但不持久化，正式代码要把依赖打进部署包（这也是你之前踩过的坑）。
"""

import logging
import json
from datetime import datetime, timezone, timedelta

import config
import market_timing
import sector_rotation
import stock_scoring
import buy_signal
import position_sizing
import position_monitor
import sell_signal  # noqa: F401  (被 position_monitor 间接使用，这里显式导入方便你调试时直接调用)
import risk_control
import github_sync

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
logger = logging.getLogger("aiquant.main_handler")

BEIJING_TZ = timezone(timedelta(hours=8))


def _now_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def run_pipeline():
    """串行执行七层框架，返回本轮完整结果（同时会写入 GitHub）。"""
    result = {"run_at": _now_str()}

    # ---- 第一/二层：先算板块，再把板块结果喂给市场情绪分 ----
    top_sectors = sector_rotation.get_top_sectors()
    market_result = market_timing.get_market_score(sector_scores=top_sectors)
    result["market_score"] = market_result
    result["top_sectors"] = top_sectors
    logger.info("市场评分 %.2f（%s），强势板块 %s", market_result["total_score"], market_result["mode"],
                [s["sector"] for s in top_sectors])

    # ---- 账户状态 / 风控（第九节）----
    account_state = github_sync.read_json("account_state.json", default={}) or {}
    positions = github_sync.read_json("positions.json", default=[]) or []
    total_capital = account_state.get("total_capital", 0) or 0

    # 需要先给每个持仓补上最新价，供风控和监控使用
    current_equity = total_capital  # 若没有实时估值管道，先用总资金占位，建议后续接入真实净值计算
    risk_result = risk_control.apply_risk_control(positions, current_equity, total_capital, account_state)
    result["risk_control"] = risk_result

    # ---- 第六层：持仓监控（无论市场评分多少，已有持仓都要盯）----
    monitor_result = position_monitor.monitor_all_positions(
        positions, market_result["total_score"], top_sector_names=[s["sector"] for s in top_sectors]
    )
    result["position_monitor"] = monitor_result

    # ---- 第三/四/五层：只有在没有触发"当日禁止新开仓"时才找新的买入机会 ----
    if risk_result["halt_new_positions"]:
        result["stock_pool"] = []
        result["new_signals"] = []
        result["position_allocation"] = {"notes": ["当日已触发风控暂停新开仓"]}
        logger.info("风控触发：本轮跳过选股与买入信号生成")
    else:
        stock_pool = stock_scoring.get_stock_pool(top_sectors)
        result["stock_pool"] = stock_pool
        signals = buy_signal.generate_buy_signals(market_result["total_score"], stock_pool)
        result["new_signals"] = signals
        allocation = position_sizing.allocate_positions(market_result, signals, current_holding_count=len(positions))
        result["position_allocation"] = allocation

    # ---- 写回 GitHub，供前端静态页面读取 ----
    ok = True
    ok &= github_sync.write_json("market_score.json", market_result, "update market_score")
    ok &= github_sync.write_json("sector_rank.json", top_sectors, "update sector_rank")
    ok &= github_sync.write_json("stock_pool.json", result.get("stock_pool", []), "update stock_pool")
    ok &= github_sync.write_json("signals.json", result.get("new_signals", []), "update signals")
    ok &= github_sync.write_json("monitor.json", monitor_result, "update monitor")
    ok &= github_sync.write_json("risk_status.json", risk_result, "update risk_status")
    ok &= github_sync.write_json("last_run.json", {"run_at": result["run_at"], "sync_ok": ok}, "update last_run")

    result["github_sync_ok"] = ok
    return result


def handler(event, context):
    """阿里云 FC 事件函数标准签名。定时触发器传入的 event 通常不需要解析。"""
    try:
        result = run_pipeline()
        logger.info("本轮流水线执行完成，GitHub 同步%s", "成功" if result.get("github_sync_ok") else "存在失败项，请查日志")
        return {"statusCode": 200, "body": json.dumps({"ok": True, "run_at": result["run_at"]}, ensure_ascii=False)}
    except Exception as e:  # noqa: BLE001 - FC 顶层必须兜底，否则一次异常会中断整个定时任务的日志追踪
        logger.exception("流水线执行异常: %s", e)
        return {"statusCode": 500, "body": json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)}


if __name__ == "__main__":
    # 本地/云端终端手动测试用：python main_handler.py
    print(json.dumps(handler({}, None), ensure_ascii=False, indent=2))
