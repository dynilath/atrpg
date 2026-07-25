"""sessions.py — /api/sessions/* 路由。

会话历史查看、回滚、用量统计。
从原有 console.py 迁移而来。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions():
    """列出所有有历史的 session。"""
    try:
        s = get_store()
        return JSONResponse(s.list_sessions())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/turns")
async def list_turns(sid: str):
    """列出某 session 的轮次摘要。"""
    try:
        s = get_store()
        return JSONResponse(s.list_turns(sid))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/usage")
async def usage_summary(sid: str):
    """总 token 用量统计。"""
    try:
        s = get_store()
        return JSONResponse(s.usage_summary(sid))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{sid}/turns/{turn_no}")
async def turn_detail(sid: str, turn_no: int):
    """某轮完整详情（含 messages）。"""
    try:
        s = get_store()
        d = s.get_turn_detail(sid, turn_no)
        if d is None:
            return JSONResponse({"error": "轮次不存在"}, status_code=404)
        return JSONResponse(d)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/{sid}/rollback/{turn_no}")
async def rollback(sid: str, turn_no: int):
    """回滚到某轮。"""
    try:
        s = get_store()
        ok = s.rollback(sid, turn_no)
        if not ok:
            return JSONResponse({"error": "回滚失败（轮次不存在）"}, status_code=404)
        return JSONResponse({"ok": True, "rolled_back_to": turn_no})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
