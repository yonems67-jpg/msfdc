# -*- coding: utf-8 -*-
"""
第二层：热点板块轮动模型
对全市场行业板块打分，只保留排名前5的强势板块，供第三层选股使用。
"""

import logging
import pandas as pd

import config
import data_source as ds

logger = logging.getLogger("aiquant.sector_rotation")


def _score_one_sector(row: pd.Series, fund_flow_rank: pd.DataFrame) -> dict:
    name = row.get("板块名称", row.get("name", ""))

    # 1. 板块资金净流入（30分）——从资金流排名表里找该板块的排名百分位
    fund_score = 0.5
    if not fund_flow_rank.empty:
        name_col = next((c for c in ["名称", "板块名称"] if c in fund_flow_rank.columns), None)
        flow_col = next((c for c in ["净额", "今日主力净流入-净额"] if c in fund_flow_rank.columns), None)
        if name_col and flow_col:
            match = fund_flow_rank[fund_flow_rank[name_col] == name]
            if not match.empty:
                rank_pct = 1 - (fund_flow_rank[flow_col].rank(ascending=False, pct=True).loc[match.index[0]])
                fund_score = rank_pct
    fund_flow_points = fund_score * config.SECTOR_FUND_FLOW_WEIGHT

    # 2. 近5日板块累计涨幅（25分）
    hist = ds.get_industry_hist(name, days=6)
    change_5d = 0.0
    if not hist.empty and "收盘" in hist.columns and len(hist) >= 2:
        change_5d = (hist["收盘"].iloc[-1] / hist["收盘"].iloc[0] - 1)
    change_points = max(0.0, min(change_5d / 0.15, 1.0)) * config.SECTOR_5D_CHANGE_WEIGHT  # 15%涨幅记满分

    # 3. 板块内涨停个股数量（20分）——需要涨停池按所属板块聚合，这里用成分股与涨停池取交集
    limit_up = ds.get_limit_up_pool()
    limitup_count = 0
    cons = ds.get_industry_constituents(name)
    if not limit_up.empty and not cons.empty:
        code_col_up = next((c for c in ["代码"] if c in limit_up.columns), None)
        code_col_cons = next((c for c in ["代码"] if c in cons.columns), None)
        if code_col_up and code_col_cons:
            limitup_count = cons[code_col_cons].isin(limit_up[code_col_up]).sum()
    limitup_points = min(limitup_count / 8, 1.0) * config.SECTOR_LIMITUP_COUNT_WEIGHT

    # 4. 板块龙头个股强度（15分）——用成分股里当日涨幅最高的个股涨幅做代理
    leader_strength_ratio = 0.5
    if not cons.empty:
        chg_col = next((c for c in ["涨跌幅"] if c in cons.columns), None)
        if chg_col:
            max_chg = pd.to_numeric(cons[chg_col], errors="coerce").max()
            leader_strength_ratio = max(0.0, min((max_chg or 0) / 10, 1.0))
    leader_points = leader_strength_ratio * config.SECTOR_LEADER_STRENGTH_WEIGHT

    # 5. 板块行情持续性（10分）——用近5日是否连续上涨的天数占比做代理
    persistence_ratio = 0.5
    if not hist.empty and "收盘" in hist.columns and len(hist) >= 3:
        diffs = hist["收盘"].diff().dropna()
        persistence_ratio = (diffs > 0).sum() / max(len(diffs), 1)
    persistence_points = persistence_ratio * config.SECTOR_PERSISTENCE_WEIGHT

    total = fund_flow_points + change_points + limitup_points + leader_points + persistence_points

    return {
        "sector": name,
        "score": round(total, 2),
        "detail": {
            "资金净流入": round(fund_flow_points, 2),
            "近5日涨幅": round(change_points, 2),
            "板块涨停数": limitup_count,
            "龙头强度": round(leader_strength_ratio, 3),
            "持续性": round(persistence_ratio, 3),
        },
        "leader_strength": round(leader_strength_ratio, 3),
        "persistence": round(persistence_ratio, 3),
    }


def get_top_sectors(top_n: int = None) -> list:
    """返回排名前 top_n（默认取 config.TOP_SECTOR_COUNT）的强势板块打分结果。"""
    top_n = top_n or config.TOP_SECTOR_COUNT
    boards = ds.get_industry_board_list()
    if boards.empty:
        logger.warning("行业板块列表为空，板块轮动模块本轮跳过")
        return []

    fund_flow_rank = ds.get_industry_fund_flow_rank()
    name_col = next((c for c in ["板块名称", "名称"] if c in boards.columns), boards.columns[0])

    scored = []
    for _, row in boards.iterrows():
        row_norm = row.rename({name_col: "板块名称"}) if name_col != "板块名称" else row
        try:
            scored.append(_score_one_sector(row_norm, fund_flow_rank))
        except Exception as e:  # noqa: BLE001
            logger.warning("板块打分失败 %s: %s", row.get(name_col), e)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
