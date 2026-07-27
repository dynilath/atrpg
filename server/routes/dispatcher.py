"""dispatcher.py --- 统一回复分发器。

处理 process_turn 产生的回复的分发：
1. 写入统一聊天记录 (chat.db)
2. 广播给所有 WebSocket 客户端
3. 由调用方决定是否发送到 QQ 群

用于实现 QQ 群聊 ↔ 网页聊天的双向互通。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core import db as _db

logger = logging.getLogger(__name__)

# 所有活跃 WebSocket 连接: uid -> list[WebSocket]
_active_connections: dict[str, list[Any]] = {}
# 控制台监控连接（不参与游戏消息）
_console_connections: list[Any] = []


async def broadcast(msg: dict) -> None:
    """向所有 WebSocket 连接（含控制台）广播一条消息。"""
    dead: list[tuple[str, Any]] = []
    for uid, socks in _active_connections.items():
        for ws in socks:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append((uid, ws))
    for uid, ws in dead:
        try:
            _active_connections.get(uid, []).remove(ws)
        except ValueError:
            pass
    # 也发给控制台连接
    dead_console: list[Any] = []
    for ws in _console_connections:
        try:
            await ws.send_json(msg)
        except Exception:
            dead_console.append(ws)
    for ws in dead_console:
        try:
            _console_connections.remove(ws)
        except ValueError:
            pass


async def send_to_uid(uid: str, msg: dict) -> None:
    """向指定 uid 的所有连接发送消息。"""
    dead: list[Any] = []
    for ws in _active_connections.get(uid, []):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _active_connections.get(uid, []).remove(ws)
        except ValueError:
            pass


def record_user_msg(root: Path, sender: str, text: str, source: str = "web") -> dict:
    """记录用户消息到 chat.db 并返回消息对象。"""
    return _db.chat_append(root, sender, text, source=source)


def record_bot_msg(root: Path, text: str) -> dict:
    """记录机器人回复到 chat.db 并返回消息对象。"""
    return _db.chat_append(root, "主持人", text, source="bot")


def record_system_msg(root: Path, text: str) -> dict:
    """记录系统消息到 chat.db 并返回消息对象。"""
    return _db.chat_append(root, "系统", text, source="system")
