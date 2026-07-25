"""ws.py — /ws/* WebSocket 路由。

实时消息推送：主持人回复流式到达（reply_chunk）。
协议（JSON）：
  客户端 → 服务端：
    { "type": "chat", "payload": { "text": "..." } }
    { "type": "edit", "payload": { "text": "..." } }
    { "type": "identify", "payload": { "provider": "web"|"qq", "openid": "..." } }
    "ping"

  服务端 → 客户端：
    { "type": "connected", "session_key": "..." }
    { "type": "reply_chunk", "payload": { "text": "..." } }
    { "type": "reply_done", "payload": { "usage": {...}, "replied": true } }
    { "type": "error", "payload": { "message": "..." } }
    { "type": "pong" }
    { "type": "heartbeat" }
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])


def _read_user_char_slug(provider: str, openid: str) -> str | None:
    """从 .atrpg/users/{provider}/{openid}.json 读取用户绑定的角色 slug。"""
    import json as _json
    from pathlib import Path
    from ..deps import get_config
    cfg = get_config()
    p = Path(cfg.game_dir) / ".atrpg" / "users" / provider / f"{openid}.json"
    if not p.exists():
        return None
    try:
        data = _json.loads(p.read_text(encoding="utf-8"))
        return data.get("character_slug")
    except (_json.JSONDecodeError, OSError):
        return None


@router.websocket("/{session_key}")
async def session_ws(websocket: WebSocket, session_key: str):
    """WebSocket 端点：实时对话协议。"""
    from bot.atrpg_gm.types import TurnInput
    from bot.atrpg_gm.process_turn import process_turn
    from ..deps import get_store

    await websocket.accept()
    await websocket.send_json({"type": "connected", "session_key": session_key})
    logger.info(f"WebSocket 已连接: {session_key}")

    # 用户身份（由客户端 identify 消息设置）
    user_provider: str = ""
    user_openid: str = ""
    user_char_slug: str | None = None

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
                continue

            # 心跳
            if raw == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            # JSON 消息
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": "无效 JSON"},
                })
                continue

            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            # 身份识别
            if msg_type == "identify":
                user_provider = (payload.get("provider") or "").strip()
                user_openid = (payload.get("id") or payload.get("openid") or "").strip()
                if user_provider and user_openid:
                    user_char_slug = _read_user_char_slug(user_provider, user_openid)
                    logger.info(
                        f"WS identify: {user_provider}:{user_openid} char={user_char_slug}"
                    )
                continue

            text = (payload.get("text") or "").strip()

            if msg_type not in ("chat", "edit"):
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": f"未知消息类型: {msg_type}"},
                })
                continue

            if not text:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": "text 不能为空"},
                })
                continue

            # ── 处理 chat / edit ──
            try:
                store = get_store()
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": f"Store 未就绪: {e}"},
                })
                continue

            # send_fn：流式推送 reply_chunk
            async def _send(content: str) -> None:
                try:
                    await websocket.send_json({
                        "type": "reply_chunk",
                        "payload": {"text": content},
                    })
                except Exception as e:
                    logger.warning(f"WS send 失败: {e}")

            # mode 区分：chat/edit
            msg_mode = msg_type  # "chat" → "game", "edit" → "edit"
            process_mode = "game" if msg_mode == "chat" else "edit"
            member_openid = (
                f"{user_provider}:{user_openid}"
                if user_provider and user_openid
                else f"ws_user_{session_key}"
            )
            group_id = session_key

            logger.info(
                f"WS msg: session={session_key} mode={process_mode} "
                f"char={user_char_slug} text={text[:60]}"
            )

            input_data = TurnInput(
                store=store,
                session_key=session_key,
                member_openid=member_openid,
                group_id=group_id,
                text=text,
                send_fn=_send,
                mode=process_mode,
                char_slug=user_char_slug,
            )
            result = await process_turn(input_data)
            logger.info(
                f"WS done: replied={result.replied} error={result.error!r} "
                f"usage={result.usage}"
            )

            await websocket.send_json({
                "type": "reply_done",
                "payload": {
                    "replied": result.replied,
                    "reply_preview": result.reply_preview,
                    "usage": result.usage,
                    "error": result.error,
                },
            })

    except WebSocketDisconnect:
        logger.info(f"WS 断开: {session_key}")
    except Exception:
        logger.exception(f"WS 异常: {session_key}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass