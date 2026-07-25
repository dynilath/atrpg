"""sessions.py — /api/sessions/* 路由。

会话历史查看、回滚、用量统计（仅管理员可访问）。
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..deps import get_store
from .users import _check_admin

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _require_admin(x_provider: str = Header("", alias="X-Provider"),
                   x_user_id: str = Header("", alias="X-User-Id")) -> None:
    """校验管理员权限。非管理员抛出 403。"""
    if not x_provider or not x_user_id:
        raise JSONResponse(
            {"error": "缺少身份标识 (X-Provider / X-User-Id)"},
            status_code=401,
        )
    if not _check_admin(x_provider, x_user_id):
        raise JSONResponse(
            {"error": "需要管理员权限"}, status_code=403
        )


def _check(x_provider: str, x_user_id: str):
    """内联权限检查（用于非装饰器场景）。"""
    if not x_provider or not x_user_id:
        return JSONResponse(
            {"error": "缺少身份标识 (X-Provider / X-User-Id)"},
            status_code=401,
        )
    if not _check_admin(x_provider, x_user_id):
        return JSONResponse({"error": "需要管理员权限"}, status_code=403)
    return None


@router.get("")
async def list_sessions(
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """列出所有有历史的 session（管理员）。"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        s = get_store()
        return JSONResponse(s.list_sessions())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/turns")
async def list_turns(
    sid: str,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """列出某 session 的轮次摘要（管理员）。"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        s = get_store()
        return JSONResponse(s.list_turns(sid))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/usage")
async def usage_summary(
    sid: str,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """总 token 用量统计（管理员）。"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        s = get_store()
        return JSONResponse(s.usage_summary(sid))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/turns/{turn_no}")
async def turn_detail(
    sid: str,
    turn_no: int,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """某轮完整详情（管理员）。"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        s = get_store()
        d = s.get_turn_detail(sid, turn_no)
        if d is None:
            return JSONResponse({"error": "轮次不存在"}, status_code=404)
        return JSONResponse(d)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/{sid}/rollback/{turn_no}")
async def rollback(
    sid: str,
    turn_no: int,
    x_provider: str = Header("", alias="X-Provider"),
    x_user_id: str = Header("", alias="X-User-Id"),
):
    """回滚到某轮（管理员）。"""
    err = _check(x_provider, x_user_id)
    if err:
        return err
    try:
        s = get_store()
        ok = s.rollback(sid, turn_no)
        if not ok:
            return JSONResponse({"error": "回滚失败（轮次不存在）"}, status_code=404)
        return JSONResponse({"ok": True, "rolled_back_to": turn_no})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
