"""users.py — /api/users/* 路由。

用户身份管理：注册/查询用户、绑定角色、权限检查。
用户数据存储在 .atrpg/users/{provider}/{openid}.json。
provider 取值：web（网页访客）、qq（QQ 机器人）等。

权限体系：
  "管理员" — config.toml 的 admin_users（系统级），可查看 LLM 后台数据
  "主持人" — 游戏目录 .atrpg/hosts.json（每局可不同），可备团编辑
  "玩家"   — 默认，可参与游戏

注意：数据文件内部字段名为 "openid"（历史兼容），
API 对外统一映射为 "id"。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..deps import get_config, get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])


def _users_dir() -> Path:
    cfg = get_config()
    d = Path(cfg.game_dir) / ".atrpg" / "users"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_path(provider: str, openid: str) -> Path:
    return _users_dir() / provider / f"{openid}.json"


def _read_user_raw(provider: str, openid: str) -> dict[str, Any] | None:
    """读取原始用户数据（文件中以 openid 为键名）。"""
    p = _user_path(provider, openid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_user(raw: dict[str, Any]) -> dict[str, Any]:
    """将原始数据标准化：openid → id，注入 permission。"""
    user_id = raw.get("id") or raw.get("openid", "")
    provider = raw.get("provider", "")

    normalized = {
        "provider": provider,
        "id": user_id,
        "display_name": raw.get("display_name", f"玩家_{user_id[:8]}"),
        "character_slug": raw.get("character_slug"),
        "permission": _resolve_permission(provider, user_id),
        "joined": raw.get("joined", ""),
    }
    return normalized


def _write_user(provider: str, openid: str, data: dict[str, Any]) -> None:
    """写入用户数据（文件中保持 openid 键名）。"""
    p = _user_path(provider, openid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _matches_user(user_spec: str, provider: str, user_id: str) -> bool:
    """检查用户是否匹配配置中的某项。
    user_spec 格式：
      - "web:abc123" → 精确匹配 provider:user_id
      - "abc123"     → 仅匹配 user_id
    """
    if ":" in user_spec:
        p, u = user_spec.split(":", 1)
        return p == provider and u == user_id
    return user_spec == user_id


def _read_hosts() -> list[str]:
    """读取本局的主持人列表（.atrpg/hosts.json）。"""
    cfg = get_config()
    p = Path(cfg.game_dir) / ".atrpg" / "hosts.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return data.get("hosts", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []


def _resolve_permission(provider: str, user_id: str) -> str:
    """根据配置解析用户权限等级。
    优先级：管理员（系统 config.toml） > 主持人（本局 .atrpg/hosts.json） > 玩家
    """
    cfg = get_config()
    for spec in cfg.web.admin_users:
        if _matches_user(spec, provider, user_id):
            return "管理员"
    for spec in _read_hosts():
        if _matches_user(spec, provider, user_id):
            return "主持人"
    return "玩家"


def _check_admin(x_provider: str, x_user_id: str) -> bool:
    """检查请求方是否为管理员（供其他路由复用）。"""
    return _resolve_permission(x_provider, x_user_id) == "管理员"


# ═══════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════


@router.post("/assign")
async def assign_user():
    """为网页访客分配一个新的用户 ID。

    服务端生成 UUID，provider 固定为 "web"。
    返回 { provider, id }，客户端应存入 localStorage。
    """
    user_id = uuid.uuid4().hex  # 32 位 hex
    raw = {
        "provider": "web",
        "openid": user_id,
        "display_name": f"玩家_{user_id[:8]}",
        "character_slug": None,
        "joined": datetime.now().strftime("%Y-%m-%d"),
    }
    _write_user("web", user_id, raw)
    logger.info(f"新用户分配: web:{user_id}")
    return JSONResponse(_normalize_user(raw))


@router.post("/register")
async def register_user(body: dict[str, Any]):
    """注册/登录用户。

    请求体：{ "provider": "web"|"qq"|..., "id"|"openid": "..." }
    如果用户已存在则返回现有数据，否则创建新用户。
    """
    provider = (body.get("provider") or "").strip()
    user_id = (body.get("id") or body.get("openid") or "").strip()
    if not provider or not user_id:
        return JSONResponse({"error": "provider 和 id 不能为空"}, status_code=400)

    existing = _read_user_raw(provider, user_id)
    if existing:
        return JSONResponse(_normalize_user(existing))

    raw = {
        "provider": provider,
        "openid": user_id,
        "display_name": f"玩家_{user_id[:8]}",
        "character_slug": None,
        "joined": datetime.now().strftime("%Y-%m-%d"),
    }
    _write_user(provider, user_id, raw)
    logger.info(f"新用户注册: {provider}:{user_id}")
    return JSONResponse(_normalize_user(raw))


@router.get("/{provider}/{openid}")
async def get_user(provider: str, openid: str):
    """获取用户信息。"""
    user = _read_user_raw(provider, openid)
    if not user:
        return JSONResponse({"error": "用户不存在"}, status_code=404)
    return JSONResponse(_normalize_user(user))


@router.put("/{provider}/{openid}/bind")
async def bind_character(provider: str, openid: str, body: dict[str, Any]):
    """绑定用户到角色。多个用户可以绑定到同一个角色。"""
    user = _read_user_raw(provider, openid)
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
    user = _read_user_raw(provider, openid)
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
    user_id = openid  # URL 参数名保持 openid（历史兼容）
    is_admin = _check_admin(provider, user_id)
    return JSONResponse({"is_admin": is_admin})
