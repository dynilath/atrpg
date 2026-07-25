"""gm.py — /api/gm/* 路由。

主持人对话：调用 process_turn 纯函数，回复通过 WebSocket 或 REST 返回。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_store

router = APIRouter(prefix="/api/gm", tags=["gm"])


@router.post("/chat")
async def gm_chat(body: dict[str, Any]):
    """主持人直接对话。

    请求体:
    {
        "text": "玩家说的话",
        "session_key": "可选（默认 auto）",
        "member_openid": "可选（默认 web_user）",
        "group_id": "可选（默认 web_group）"
    }
    返回: { replied, reply_preview, replies: [...], usage, error }
    """
    from bot.atrpg_gm.types import TurnInput

    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text 不能为空"}, status_code=400)

    session_key = body.get("session_key", "web_single")
    member_openid = body.get("member_openid", "web_user")
    group_id = body.get("group_id", session_key)

    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    collected_replies: list[str] = []

    async def _send(content: str) -> None:
        collected_replies.append(content)

    input_data = TurnInput(
        store=s,
        session_key=session_key,
        member_openid=member_openid,
        group_id=group_id,
        text=text,
        send_fn=_send,
    )
    from bot.atrpg_gm.process_turn import process_turn
    result = await process_turn(input_data)

    return JSONResponse({
        "replied": result.replied,
        "reply_preview": result.reply_preview,
        "replies": collected_replies,
        "usage": result.usage,
        "error": result.error,
    })
