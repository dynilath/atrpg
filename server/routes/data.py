"""data.py --- /api/data/* 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from server.deps import get_store

logger = logging.getLogger(__name__)


def _json_safe(obj: Any) -> Any:
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
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        docs = s.list_docs(kind)
        logger.debug(f"list {kind}: {len(docs)} 条")
        return JSONResponse(_json_safe(docs))
    except Exception as e:
        logger.exception(f"list {kind} 失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{kind}/{slug}")
async def read_doc(kind: str, slug: str):
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        d = s.read(kind, slug)
        if d is None:
            logger.debug(f"read {kind}/{slug}: 不存在")
            return JSONResponse({"error": "不存在"}, status_code=404)
        meta, body = d
        logger.debug(f"read {kind}/{slug}: ok body={len(body)}chars")
        return JSONResponse({"meta": _json_safe(meta), "body": body})
    except Exception as e:
        logger.exception(f"read {kind}/{slug} 失败")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/{kind}/{slug}")
async def write_doc(kind: str, slug: str, body: dict[str, Any]):
    if kind not in DATA_KINDS:
        return JSONResponse({"error": f"未知类别: {kind}"}, status_code=400)
    try:
        s = get_store()
        meta = body.get("meta", {})
        content = body.get("body", "")
        p = s.write(kind, slug, meta, content)
        logger.info(f"write {kind}/{slug}: ok path={p}")
        return JSONResponse({"ok": True, "path": str(p)})
    except Exception as e:
        logger.exception(f"write {kind}/{slug} 失败")
        return JSONResponse({"error": str(e)}, status_code=500)
