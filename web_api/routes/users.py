"""users.py — /api/users/* 路由。

用户身份管理：注册/查询用户、绑定角色、管理员检查。
用户数据存储在 .atrpg/users/{provider}/{openid}.json。
provider 取值：web（网页访客）、qq（QQ 机器人）等。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_config, get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])


def _users_dir() -> Path:
    """获取 .atrpg/users/ 目录路径。"""
    cfg = get_config()
    d = Path(cfg.game_dir) / ".atrpg" / "users"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_path(provider: str, openid: str) -> Path:
    return _users_dir() / provider / f"{openid}.json"


def _read_user(provider: str, openid: str) -> dict[str, Any] | None:
    """读取用户数据。"""
    p = _user_path(provider, openid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_user(provider: str, openid: str, data: dict[str, Any]) -> None:
    """写入用户数据。"""
    p = _user_path(provider, openid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_admin(provider: str, openid: str) -> bool:
    """检查用户是否为管理员。

    匹配规则：config 中的 admin_users 可以写：
      - "web:abc123" → 精确匹配 provider:openid
      - "qq:xxx"     → 精确匹配
      - "abc123"     → 仅匹配 openid（向后兼容）
    """
    cfg = get_config()
    admins = cfg.web.admin_users
    full = f"{provider}:{openid}"
    return full in admins or openid in admins


@router.post("/assign")
async def assign_user():
    """为网页访客分配一个新的用户 ID。

    服务端生成 UUID 作为 openid，provider 固定为 "web"。
    返回 { provider, openid }，客户端应存入 localStorage。
    """
    openid = uuid.uuid4().hex  # 32 位 hex
    data = {
        "provider": "web",
        "openid": openid,
        "display_name": f"玩家_{openid[:8]}",
        "character_slug": None,
        "permission": "玩家",
        "joined": datetime.now().strftime("%Y-%m-%d"),
        "is_admin": _is_admin("web", openid),
    }
    _write_user("web", openid, data)
    logger.info(f"新用户分配: web:{openid}")
    return JSONResponse(data)


@router.post("/register")
async def register_user(body: dict[str, Any]):
    """注册/登录用户。

    请求体：{ "provider": "web"|"qq"|..., "openid": "..." }
    如果用户已存在则返回现有数据，否则创建新用户。
    """
    provider = (body.get("provider") or "").strip()
    openid = (body.get("openid") or "").strip()
    if not provider or not openid:
        return JSONResponse({"error": "provider 和 openid 不能为空"}, status_code=400)

    existing = _read_user(provider, openid)
    if existing:
        existing["is_admin"] = _is_admin(provider, openid)
        return JSONResponse(existing)

    data = {
        "provider": provider,
        "openid": openid,
        "display_name": f"玩家_{openid[:8]}",
        "character_slug": None,
        "permission": "玩家",
        "joined": datetime.now().strftime("%Y-%m-%d"),
        "is_admin": _is_admin(provider, openid),
    }
    _write_user(provider, openid, data)
    logger.info(f"新用户注册: {provider}:{openid}")
    return JSONResponse(data)


@router.get("/{provider}/{openid}")
async def get_user(provider: str, openid: str):
    """获取用户信息。"""
    user = _read_user(provider, openid)
    if not user:
        return JSONResponse({"error": "用户不存在"}, status_code=404)
    user["is_admin"] = _is_admin(provider, openid)
    return JSONResponse(user)


@router.put("/{provider}/{openid}/bind")
async def bind_character(provider: str, openid: str, body: dict[str, Any]):
    """绑定用户到角色。多个用户可以绑定到同一个角色。"""
    user = _read_user(provider, openid)
    if not user:
        return JSONResponse({"error": "用户不存在"}, status_code=404)

    char_slug = (body.get("character_slug") or "").strip()
    user["character_slug"] = char_slug if char_slug else None
    _write_user(provider, openid, user)
    logger.info(f"用户 {provider}:{openid} 绑定角色: {char_slug}")
    return JSONResponse({"ok": True, "character_slug": user["character_slug"]})


@router.put("/{provider}/{openid}/display-name")
async def update_display_name(provider: str, openid: str, body: dict[str, Any]):
    """更新用户显示名称。"""
    user = _read_user(provider, openid)
    if not user:
        return JSONResponse({"error": "用户不存在"}, status_code=404)

    name = (body.get("display_name") or "").strip()
    if name:
        user["display_name"] = name
    _write_user(provider, openid, user)
    return JSONResponse({"ok": True, "display_name": user["display_name"]})


@router.get("/{provider}/{openid}/is-admin")
async def check_admin(provider: str, openid: str):
    """检查用户是否为管理员。"""
    return JSONResponse({"is_admin": _is_admin(provider, openid)})