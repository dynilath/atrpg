"""sessions.py — /api/sessions/* 路由。会话树浏览与管理（管理员）。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..deps import get_config
from .users import _check_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _check(x_provider: str, x_user_id: str):
    if not x_provider or not x_user_id:
        return JSONResponse({"error": "缺少身份标识"}, status_code=401)
    if not _check_admin(x_provider, x_user_id):
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    return None


@router.get("")
async def list_turns(
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        from bot.atrpg_gm import db as _db
        root = Path(get_config().game_dir)
        turns = _db.session_list_turns(root)
        return JSONResponse(turns)
    except Exception as e:
        logger.exception("list turns 失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{turn_id}")
async def turn_detail(
    turn_id: str,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        from bot.atrpg_gm import db as _db
        root = Path(get_config().game_dir)
        detail = _db.session_get_turn_detail(root, turn_id)
        if detail is None:
            return JSONResponse({"error": "轮次不存在"}, status_code=404)
        return JSONResponse(detail)
    except Exception as e:
        logger.exception("turn detail 失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/branch")
async def create_branch(
    body: dict,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """从指定节点创建新分支并切换。 body: {from_node_id, name?}"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        from bot.atrpg_gm import db as _db
        root = Path(get_config().game_dir)
        node_id = body.get("from_node_id", "").strip()
        name = body.get("name", "").strip() or None
        if not node_id:
            return JSONResponse({"error": "缺少 from_node_id"}, status_code=400)
        branch_id = _db.session_create_branch(root, node_id, name)
        if branch_id is None:
            return JSONResponse({"error": "节点不存在"}, status_code=404)
        return JSONResponse({"ok": True, "branch_id": branch_id})
    except Exception as e:
        logger.exception("create branch 失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/branch/active")
async def active_branch(
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        from bot.atrpg_gm import db as _db
        root = Path(get_config().game_dir)
        bid = _db.session_get_active_branch(root)
        return JSONResponse({"branch_id": bid})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/branch/switch")
async def switch_branch(
    body: dict,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """切换到指定分支。 body: {branch_id}"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        from bot.atrpg_gm import db as _db
        root = Path(get_config().game_dir)
        branch_id = body.get("branch_id", "").strip()
        if not branch_id:
            return JSONResponse({"error": "缺少 branch_id"}, status_code=400)
        ok = _db.session_switch_branch(root, branch_id)
        if not ok:
            return JSONResponse({"error": "分支不存在"}, status_code=404)
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.exception("switch branch 失败")
        return JSONResponse({"error": str(e)}, status_code=500)
