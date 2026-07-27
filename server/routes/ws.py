"""ws.py --- /ws WebSocket 路由。

端点: ws://host/ws?uid={userId}
同一游戏目录下所有连接共享聊天室，uid 区分用户身份。

协议：
  客户端 -> 服务端:
    {"type":"identify","payload":{"provider":"web","openid":"..."}}
    {"type":"chat","payload":{"text":"..."}}
    "ping"

  服务端 -> 客户端:
    {"type":"connected"}
    {"type":"chat_history","payload":{"messages":[...]}}
    {"type":"chat_msg","payload":{"id":...,"ts":"...","sender":"...","text":"...","source":"..."}}
    {"type":"reply_chunk","payload":{"text":"..."}}
    {"type":"reply_done","payload":{"replied":true,"usage":{...},"error":""}}
    {"type":"error","payload":{"message":"..."}}
    "pong"
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from server.deps import get_config, get_store
from core import db as _db
from core.types import TurnInput
from core.process_turn import process_turn
from .dispatcher import _active_connections, broadcast, send_to_uid

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)


def _read_user_char_slug(provider: str, openid: str) -> str | None:
    """从 .atrpg/users/{provider}/{openid}.json 读取用户绑定的角色 slug。"""
    cfg = get_config()
    p = Path(cfg.game_dir) / ".atrpg" / "users" / provider / f"{openid}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("character_slug")
    except (json.JSONDecodeError, OSError):
        return None


@router.websocket("")
async def session_ws(websocket: WebSocket, uid: str = Query("")):
    """WebSocket 端点：游戏聊天室。"""
    await websocket.accept()
    await websocket.send_json({"type": "connected"})
    logger.info(f"WS 连接: uid={uid}")

    # 注册连接
    if uid not in _active_connections:
        _active_connections[uid] = []
    _active_connections[uid].append(websocket)

    # 用户身份
    user_provider: str = ""
    user_openid: str = ""
    user_char_slug: str | None = None
    user_display_name: str = f"玩家_{uid[:8]}"

    # 推送最近聊天历史
    try:
        cfg = get_config()
        root = Path(cfg.game_dir)
        history = _db.chat_recent(root, limit=50)
        if history:
            await websocket.send_json({"type": "chat_history", "payload": {"messages": history}})
    except Exception:
        logger.warning("加载聊天历史失败", exc_info=True)

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

            if raw == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "payload": {"message": "无效 JSON"}})
                continue

            msg_type = msg.get("type", "")
            payload = msg.get("payload", {})

            # --- identify ---
            if msg_type == "identify":
                user_provider = (payload.get("provider") or "").strip()
                user_openid = (payload.get("id") or payload.get("openid") or "").strip()
                if user_provider and user_openid:
                    user_char_slug = _read_user_char_slug(user_provider, user_openid)
                    # 读 display_name
                    try:
                        cfg2 = get_config()
                        p = Path(cfg2.game_dir) / ".atrpg" / "users" / user_provider / f"{user_openid}.json"
                        if p.exists():
                            ud = json.loads(p.read_text(encoding="utf-8"))
                            user_display_name = ud.get("display_name", user_display_name)
                    except Exception:
                        pass
                    logger.info(f"WS identify: {user_provider}:{user_openid} char={user_char_slug}")
                continue

            # --- chat ---
            if msg_type != "chat":
                await websocket.send_json({"type": "error", "payload": {"message": f"未知消息类型: {msg_type}"}})
                continue

            text = (payload.get("text") or "").strip()
            if not text:
                continue

            # 重新读取绑定关系（可能在 identify 之后发生了解绑/绑定）
            if user_provider and user_openid:
                user_char_slug = _read_user_char_slug(user_provider, user_openid)

            # 构造发送者名称
            sender_name = f"{user_char_slug}（{user_display_name}）" if user_char_slug else user_display_name

            # 写聊天室
            try:
                cfg2 = get_config()
                root = Path(cfg2.game_dir)
                chat_msg = _db.chat_append(root, sender_name, text, source="web")
                # 广播给所有连接
                await broadcast({"type": "broadcast_chat_msg", "payload": chat_msg})
            except Exception as e:
                logger.exception("聊天室写入失败")
                await websocket.send_json({"type": "error", "payload": {"message": f"聊天室写入失败: {e}"}})
                continue

            # --- 触发 LLM ---
            try:
                s = get_store()
            except Exception as e:
                await websocket.send_json({"type": "error", "payload": {"message": f"Store 未就绪: {e}"}})
                continue

            session_key = "main"
            member_openid = f"{user_provider}:{user_openid}" if user_provider and user_openid else f"ws:{uid}"
            group_id = session_key

            # send_fn: 收集全量文本并流式推送给发送者
            full_reply: list[str] = []

            async def _send(content: str) -> None:
                full_reply.append(content)
                await send_to_uid(uid, {"type": "reply_chunk", "payload": {"text": content}})

            logger.info(f"WS chat: uid={uid} char={user_char_slug} text={text[:60]}")

            input_data = TurnInput(
                store=s,
                session_key=session_key,
                member_openid=member_openid,
                group_id=group_id,
                text=text,
                send_fn=_send,
                mode="game",
                char_slug=user_char_slug,
            )
            result = await process_turn(input_data)

            # 写 AI 回复到聊天室并广播
            if result.replied and full_reply:
                try:
                    full_text = "".join(full_reply)
                    bot_msg = _db.chat_append(root, "主持人", full_text, source="bot")
                    await broadcast({"type": "broadcast_chat_msg", "payload": bot_msg})
                except Exception:
                    logger.warning("Bot 回复写入聊天室失败", exc_info=True)

            # 保存 LLM 会话快照
            try:
                if result.messages:
                    node = _db.session_save_turn(
                        root,
                        result.messages,
                        meta={
                            "timestamp": __import__("datetime").datetime.now().isoformat(),
                            "sender": user_display_name,
                            "player_text": text[:120],
                            "reply_preview": result.reply_preview,
                            "usage": result.usage,
                            "turn_messages": result.turn_messages,
                        },
                    )
                    # 通知所有 WS 客户端（控制台刷新）
                    if node:
                        await broadcast({
                            "type": "new_turn",
                            "payload": {
                                "id": node["id"],
                                "turn_no": node["turn_no"],
                                "sender": user_display_name,
                                "player_text": text[:120],
                                "reply_preview": result.reply_preview,
                                "usage": result.usage,
                                "branch_id": node["branch_id"],
                                "parent_id": node["parent_id"],
                            },
                        })
            except Exception:
                logger.warning("会话快照保存失败", exc_info=True)

            # 通知所有同 uid 连接
            await send_to_uid(uid, {
                "type": "reply_done",
                "payload": {
                    "replied": result.replied,
                    "reply_preview": result.reply_preview,
                    "usage": result.usage,
                    "error": result.error,
                },
            })
            logger.info(f"WS done: replied={result.replied} error={result.error!r}")

    except WebSocketDisconnect:
        logger.info(f"WS 断开: uid={uid}")
    except Exception:
        logger.exception(f"WS 异常: uid={uid}")
    finally:
        # 注销连接
        try:
            _active_connections.get(uid, []).remove(websocket)
            if not _active_connections.get(uid):
                del _active_connections[uid]
        except (ValueError, KeyError):
            pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/console")
async def console_ws(websocket: WebSocket):
    """WebSocket 端点：控制台监控，只接收广播，不处理游戏消息。"""
    await websocket.accept()
    logger.info("WS 控制台连接")
    from .dispatcher import _console_connections
    _console_connections.append(websocket)
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
            if raw == "ping":
                await websocket.send_json({"type": "pong"})
    except Exception:
        pass
    finally:
        try:
            _console_connections.remove(websocket)
        except ValueError:
            pass
