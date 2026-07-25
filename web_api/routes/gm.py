"""gm.py — /api/gm/* 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gm", tags=["gm"])


@router.post("/chat")
async def gm_chat(body: dict[str, Any]):
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text 不能为空"}, status_code=400)

    session_key = body.get("session_key", "web_single")
    member_openid = body.get("member_openid", "web_user")
    group_id = body.get("group_id", session_key)

    try:
        s = get_store()
    except Exception as e:
        logger.exception("GM chat: get_store 失败")
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    collected_replies: list[str] = []

    async def _send(content: str) -> None:
        collected_replies.append(content)

    from bot.atrpg_gm.types import TurnInput
    from bot.atrpg_gm.process_turn import process_turn

    input_data = TurnInput(
        store=s,
        session_key=session_key,
        member_openid=member_openid,
        group_id=group_id,
        text=text,
        send_fn=_send,
    )
    logger.info(f"GM chat: session={session_key} user={member_openid} text={text[:80]}")
    result = await process_turn(input_data)
    logger.info(
        f"GM chat done: replied={result.replied} replies={len(collected_replies)} "
        f"usage={result.usage} error={result.error!r}"
    )

    return JSONResponse({
        "replied": result.replied,
        "reply_preview": result.reply_preview,
        "replies": collected_replies,
        "usage": result.usage,
        "error": result.error,
    })
