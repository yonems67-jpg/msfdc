# -*- coding: utf-8 -*-
"""
第十一节：数据存储与同步机制
通过 GitHub REST API（Contents API）远程读写 site/data/ 目录下的 json 文件，
不在阿里云函数本地落地持久文件（FC 的本地磁盘执行完即销毁，不可作为持久存储）。

环境变量（在阿里云函数控制台的"环境变量"里配置，不要写死在代码里）：
  GITHUB_TOKEN  - 具有目标仓库 repo 写权限的 Personal Access Token
  GITHUB_REPO   - "your-name/your-repo"
  GITHUB_BRANCH - 默认 main
"""

import base64
import json
import logging

import requests

import config

logger = logging.getLogger("aiquant.github_sync")

API_ROOT = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _full_path(relative_path: str) -> str:
    return f"{config.DATA_DIR_IN_REPO}/{relative_path.lstrip('/')}"


def read_json(relative_path: str, default=None):
    """读取仓库里的 json 文件，读不到就返回 default（不抛异常）。"""
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        logger.warning("GITHUB_TOKEN / GITHUB_REPO 未配置，跳过读取 %s", relative_path)
        return default

    url = f"{API_ROOT}/repos/{config.GITHUB_REPO}/contents/{_full_path(relative_path)}"
    try:
        resp = requests.get(
            url, headers=_headers(), params={"ref": config.GITHUB_BRANCH}, timeout=config.GITHUB_API_TIMEOUT
        )
        if resp.status_code == 404:
            return default
        resp.raise_for_status()
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 GitHub 文件失败 %s: %s", relative_path, e)
        return default


def write_json(relative_path: str, data, commit_message: str = None) -> bool:
    """写入（新建或更新）仓库里的 json 文件。返回 True/False 表示是否成功。"""
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        logger.error("GITHUB_TOKEN / GITHUB_REPO 未配置，无法写入 %s", relative_path)
        return False

    url = f"{API_ROOT}/repos/{config.GITHUB_REPO}/contents/{_full_path(relative_path)}"
    commit_message = commit_message or f"update {relative_path} via aiquant"

    sha = None
    try:
        existing = requests.get(
            url, headers=_headers(), params={"ref": config.GITHUB_BRANCH}, timeout=config.GITHUB_API_TIMEOUT
        )
        if existing.status_code == 200:
            sha = existing.json().get("sha")
        elif existing.status_code not in (404,):
            logger.warning("查询已有文件 sha 时出现异常状态码 %s: %s", existing.status_code, existing.text)
    except Exception as e:  # noqa: BLE001
        logger.warning("查询已有文件 sha 失败（将尝试直接新建）: %s", e)

    payload = {
        "message": commit_message,
        "content": base64.b64encode(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": config.GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=_headers(), json=payload, timeout=config.GITHUB_API_TIMEOUT)
        if resp.status_code not in (200, 201):
            logger.error("写入 GitHub 文件失败 %s: HTTP %s %s", relative_path, resp.status_code, resp.text)
            return False
        return True
    except requests.exceptions.Timeout:
        logger.error("写入 GitHub 文件超时: %s", relative_path)
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("写入 GitHub 文件时网络异常 %s: %s", relative_path, e)
        return False
