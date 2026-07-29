# -*- coding: utf-8 -*-
"""
数据层：所有 AKShare 调用统一收口在这里。

⚠️ 重要提示（请上传前务必阅读 README 里的"验证清单"）：
本文件里的 AKShare 接口名 / 字段名是按 AKShare 常见版本写的，但 AKShare 更新很频繁，
东方财富/新浪的页面结构也会变。开发沙箱环境没有访问 eastmoney/sina 财经接口的网络权限，
所以这些函数在写完之后**没有能力实机验证**。第一次部署到阿里云后，请先单独跑一遍
`python -c "import data_source; print(data_source.get_index_daily('sh000001').tail())"`
之类的小测试，把跑不通的接口名换成你本地 pip show akshare 版本里实际存在的名字。

所有函数遵循同一个约定：拿不到数据就返回 None 或空 DataFrame，绝不抛异常炸掉整条流水线，
上层调用者要自己处理"这层数据缺失"的降级逻辑（通常是该子项打0分，而不是整体崩溃）。
"""

import logging
import pandas as pd
import akshare as ak

from config import HTTP_TIMEOUT

logger = logging.getLogger("aiquant.data_source")


def _safe_call(func_name: str, *args, **kwargs):
    """
    统一的容错包装：按函数名字符串在 akshare 模块里查找并调用。
    注意：函数查找（getattr）本身也放在 try 里 —— 如果某个 AKShare 版本把接口改名/删掉了，
    这里只会记一条日志、返回 None，不会让 AttributeError 冒出去炸掉整条流水线。
    """
    try:
        func = getattr(ak, func_name)
        return func(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - 数据源问题不应该让整条流水线崩溃
        logger.warning("AKShare 调用失败 %s(%s, %s): %s", func_name, args, kwargs, e)
        return None


# ---------------------------------------------------------------------------
# 指数数据
# ---------------------------------------------------------------------------
def get_index_daily(symbol: str, lookback: int = 90) -> pd.DataFrame:
    """获取指数日线并附加 MA5/MA20/MA60。symbol 例如 'sh000001'。"""
    df = _safe_call("stock_zh_index_daily", symbol=symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.tail(lookback).reset_index(drop=True)
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    return df


# ---------------------------------------------------------------------------
# 全市场涨跌停 / 赚钱效应
# ---------------------------------------------------------------------------
def get_limit_up_pool() -> pd.DataFrame:
    """今日涨停股池，含连板数字段（AKShare 字段名常见为 '连板数'）。"""
    df = _safe_call("stock_zt_pool_em")
    return df if df is not None else pd.DataFrame()


def get_limit_down_pool() -> pd.DataFrame:
    """今日跌停股池。"""
    df = _safe_call("stock_zt_pool_dtgc_em")
    return df if df is not None else pd.DataFrame()


def get_market_spot() -> pd.DataFrame:
    """全市场实时行情快照（用于计算上涨家数占比、全市场成交额等）。"""
    df = _safe_call("stock_zh_a_spot_em")
    return df if df is not None else pd.DataFrame()


# ---------------------------------------------------------------------------
# 板块数据
# ---------------------------------------------------------------------------
def get_industry_board_list() -> pd.DataFrame:
    """行业板块列表及涨跌幅/资金流排名。"""
    df = _safe_call("stock_board_industry_name_em")
    return df if df is not None else pd.DataFrame()


def get_industry_fund_flow_rank(indicator: str = "今日") -> pd.DataFrame:
    """行业资金流排名，用于板块资金净流入打分。"""
    df = _safe_call("stock_sector_fund_flow_rank", indicator=indicator, sector_type="行业资金流")
    return df if df is not None else pd.DataFrame()


def get_industry_hist(symbol: str, days: int = 10) -> pd.DataFrame:
    """单个行业板块的历史日线，用于计算近5日累计涨幅。"""
    df = _safe_call("stock_board_industry_hist_em", symbol=symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    return df.tail(days).reset_index(drop=True)


def get_industry_constituents(symbol: str) -> pd.DataFrame:
    """行业板块成分股。"""
    df = _safe_call("stock_board_industry_cons_em", symbol=symbol)
    return df if df is not None else pd.DataFrame()


# ---------------------------------------------------------------------------
# 个股数据
# ---------------------------------------------------------------------------
def get_stock_fund_flow(code: str) -> pd.DataFrame:
    """个股近期主力资金流水（用于连续净流入/流出判断）。"""
    df = _safe_call("stock_individual_fund_flow", stock=code)
    return df if df is not None else pd.DataFrame()


def get_stock_daily(code: str, lookback: int = 90) -> pd.DataFrame:
    """个股日线，附加 MA5/MA10/MA20，用于趋势因子和均线破位判断。"""
    df = _safe_call("stock_zh_a_hist", symbol=code, period="daily", adjust="qfq")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.tail(lookback).reset_index(drop=True)
    df = df.rename(columns={"收盘": "close", "成交量": "volume", "日期": "date"})
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    return df


def get_stock_realtime_quote(codes: list) -> pd.DataFrame:
    """批量个股实时行情快照，用于5分钟持仓监控。"""
    spot = get_market_spot()
    if spot.empty:
        return pd.DataFrame()
    code_col = "代码" if "代码" in spot.columns else spot.columns[0]
    return spot[spot[code_col].isin(codes)].reset_index(drop=True)
