"""deps.py --- FastAPI 依赖注入。

提供 get_store / get_config 等公共依赖，
供各路由模块使用。
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

from fastapi import Request

from core.config import AppConfig, load_config

# 应用级单例
_config: AppConfig | None = None
_store: object | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_store():
    """获取 Store 实例（延迟初始化，单例）。"""
    global _store
    if _store is None:
        cfg = get_config()
        from core.store import Store
        _store = Store(cfg.game_dir)
    return _store


async def resolve_store(request: Request):
    """FastAPI 路由依赖：注入 Store 实例。"""
    return get_store()
