"""data.py — /api/data/* 路由。

data/ 目录下游戏档案的 CRUD（角色/NPC/场景/地点/道具/弧光等）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_store


def _json_safe(obj: Any) -> Any:
    """递归将不可 JSON 序列化的类型转为字符串。"""
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


router = APIRouter(prefix="/api/data", tags=["data"])

DATA_KINDS = (
    "characters", "npcs", "locations", "scenes", "items",
    "story-arcs", "state-records", "sessions", "players",
)


@router.get("/{kind}")
async def list_docs(kind: str):
    """列出某类数据档案摘要。"""
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs(kind)))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{kind}/{slug}")
async def read_doc(kind: str, slug: str):
    """读取完整档案（meta + body）。"""
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        d = s.read(kind, slug)
        if d is None:
            return JSONResponse({"error": "不存在"}, status_code=404)
        meta, body = d
        return JSONResponse({"meta": _json_safe(meta), "body": body})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/{kind}/{slug}")
async def write_doc(kind: str, slug: str, body: dict[str, Any]):
    """写入/更新档案。body 格式: {"meta": {...}, "body": "..."}"""
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        meta = body.get("meta", {})
        content = body.get("body", "")
        p = s.write(kind, slug, meta, content)
        return JSONResponse({"ok": True, "path": str(p)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
