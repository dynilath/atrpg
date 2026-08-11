"""gm.py --- /api/gm/* 路由。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from server.deps import get_store
from server.routes.users import require_host
from core import db as _db
from core.types import TurnInput
from core.process_turn import process_turn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gm", tags=["gm"])


@router.post("/chat")
async def gm_chat(body: dict[str, Any], _: None = Depends(require_host)):
    """主持人手动推进剧情（GM 模式）。需主持人/管理员权限。"""
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

    # 保存本轮消息（与 ws.py/qqbot.py 一致），否则多轮上下文无法累积
    try:
        if result.turn_messages:
            node = _db.session_save_turn(
                s.root,
                result.turn_messages,
                meta={
                    "timestamp": datetime.now().isoformat(),
                    "sender": member_openid,
                    "player_text": text[:120],
                    "reply_preview": result.reply_preview,
                    "usage": result.usage,
                    "llm_calls": result.llm_calls,
                    "total_msgs": result.total_msgs,
                },
            )
            logger.info(f"GM chat: turn 已保存 node={node.get('turn_no') if node else None}")
    except Exception:
        logger.warning("GM chat: 会话快照保存失败", exc_info=True)

    return JSONResponse({
        "replied": result.replied,
        "reply_preview": result.reply_preview,
        "replies": collected_replies,
        "usage": result.usage,
        "llm_calls": result.llm_calls,
        "total_msgs": result.total_msgs,
        "error": result.error,
    })
