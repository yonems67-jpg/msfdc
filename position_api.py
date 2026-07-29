# -*- coding: utf-8 -*-
"""
阿里云函数计算 —— "HTTP函数"入口，供网页端的持仓录入表单调用。

这个函数要单独建一个 FC 函数（跟 main_handler 的定时函数分开），
运行时选择 "自定义运行时 / HTTP函数"，入口填 `position_api.handler`，
并绑定一个 HTTP 触发器（阿里云会给你一个形如
https://xxxx.cn-hangzhou.fc.aliyuncs.com/2016-08-15/proxy/xxx/xxx/ 的公网地址）。

前端 web/positions.html 里的 API_BASE_URL 常量要填成这个地址。

支持的接口（都在同一个 URL 下，用 method + path 区分）：
  GET  /positions        -> 返回当前持仓列表
  POST /positions        -> 新增一条持仓，body 为 json: {code, cost_price, quantity, sector}
  PUT  /positions/<code> -> 更新某只持仓（按代码匹配）
  DELETE /positions/<code> -> 删除某只持仓

出于个人自用场景的最低限度安全考虑：请在环境变量里配置 API_SECRET，
前端请求头需要带 `X-Api-Secret`，不匹配则拒绝，避免这个公网 URL 被任何人扫到就能改你的持仓数据。
"""

import json
import os
import logging

import github_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aiquant.position_api")

API_SECRET = os.environ.get("API_SECRET", "")
POSITIONS_FILE = "positions.json"

CORS_HEADERS = [
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, X-Api-Secret"),
]


def _json_response(start_response, status_code: int, payload) -> list:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8")] + CORS_HEADERS
    start_response(f"{status_code} {'OK' if status_code < 300 else 'ERROR'}", headers)
    return [body]


def _check_secret(environ) -> bool:
    if not API_SECRET:
        return True  # 没配置密钥就不校验（不建议在生产使用，仅方便本地联调）
    provided = environ.get("HTTP_X_API_SECRET", "")
    return provided == API_SECRET


def _read_body(environ) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
    except ValueError:
        length = 0
    if length == 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    return json.loads(raw.decode("utf-8")) if raw else {}


def handler(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/").rstrip("/")

    if method == "OPTIONS":
        start_response("204 No Content", CORS_HEADERS)
        return [b""]

    if not _check_secret(environ):
        return _json_response(start_response, 401, {"ok": False, "error": "invalid or missing X-Api-Secret"})

    positions = github_sync.read_json(POSITIONS_FILE, default=[]) or []

    try:
        if method == "GET" and path in ("", "/positions"):
            return _json_response(start_response, 200, {"ok": True, "positions": positions})

        if method == "POST" and path in ("", "/positions"):
            body = _read_body(environ)
            required = {"code", "cost_price", "quantity"}
            if not required.issubset(body):
                return _json_response(start_response, 400, {"ok": False, "error": f"缺少必填字段: {required}"})
            positions.append({
                "code": body["code"],
                "cost_price": float(body["cost_price"]),
                "quantity": int(body["quantity"]),
                "sector": body.get("sector"),
                "opened_at": body.get("opened_at"),
            })
            ok = github_sync.write_json(POSITIONS_FILE, positions, f"add position {body['code']}")
            return _json_response(start_response, 200 if ok else 500, {"ok": ok, "positions": positions})

        if method == "PUT" and path.startswith("/positions/"):
            code = path.split("/positions/", 1)[1]
            body = _read_body(environ)
            found = False
            for p in positions:
                if p["code"] == code:
                    p.update({k: v for k, v in body.items() if k in ("cost_price", "quantity", "sector")})
                    found = True
            if not found:
                return _json_response(start_response, 404, {"ok": False, "error": f"未找到持仓 {code}"})
            ok = github_sync.write_json(POSITIONS_FILE, positions, f"update position {code}")
            return _json_response(start_response, 200 if ok else 500, {"ok": ok, "positions": positions})

        if method == "DELETE" and path.startswith("/positions/"):
            code = path.split("/positions/", 1)[1]
            new_positions = [p for p in positions if p["code"] != code]
            if len(new_positions) == len(positions):
                return _json_response(start_response, 404, {"ok": False, "error": f"未找到持仓 {code}"})
            ok = github_sync.write_json(POSITIONS_FILE, new_positions, f"remove position {code}")
            return _json_response(start_response, 200 if ok else 500, {"ok": ok, "positions": new_positions})

        return _json_response(start_response, 404, {"ok": False, "error": f"未知路由 {method} {path}"})

    except Exception as e:  # noqa: BLE001
        logger.exception("position_api 处理请求异常: %s", e)
        return _json_response(start_response, 500, {"ok": False, "error": str(e)})
