"""qqbot.py --- QQ Bot 适配层（基于 qqbot-agent-sdk）。

在 FastAPI lifespan 中启动/停止，复用主 asyncio 事件循环。
替代 NoneBot 全家桶，仅依赖腾讯官方 SDK。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from core.store import Store, StoreError
from core.types import TurnInput
from core.process_turn import process_turn, _split_chunks
from core import db as _db
from core.config import load_config

# 导入 tools 触发注册
from core import tools  # noqa: F401

logger = logging.getLogger("atrpg.qqbot")


class QQBotManager:
    """QQ Bot 生命周期管理。"""

    def __init__(self):
        self._ws = None
        self._api = None
        self._running = False

    async def start(self) -> bool:
        """启动 QQ Bot：连接 WebSocket 网关，开始接收消息。返回是否成功启动。"""
        cfg = load_config()
        bots = self._load_bots()
        if not bots:
            logger.info("QQ Bot 凭据未配置，跳过")
            return False

        app_id, client_secret = bots[0]

        from qqbot_agent_sdk import (
            QQApiClient, QQWebSocket, WSCallbacks,
            EventParser, EventType, InboundEvent,
        )

        self._api = QQApiClient(app_id=app_id, client_secret=client_secret)
        await self._api.ensure_token()

        # setup HTTP client for async API calls
        # trust_env=False：QQ Bot 为国内直连服务，绕过系统代理（Clash 等会中断 TLS）
        import httpx
        self._api.setup(httpx.AsyncClient(trust_env=False))

        store = Store(cfg.game_dir)

        async def on_message(event_type: str, raw: dict):
            logger.debug(f"QQ事件: {event_type} raw_keys={list(raw.keys())[:5]}")
            event: InboundEvent = EventParser().parse(event_type, raw)
            if not event:
                logger.debug(f"QQ事件解析失败: {event_type}")
                return

            logger.debug(
                f"QQ消息: type={event_type} scope={event.chat_scope} "
                f"user={event.user_name}({event.user_id[:8]}...) "
                f"content={event.content[:50]!r}"
            )

            # 只处理群 @ 消息和 C2C 私聊
            if event_type == EventType.GROUP_AT_MESSAGE_CREATE:
                await self._handle_group_message(store, event, cfg)
            elif event_type == EventType.C2C_MESSAGE_CREATE:
                if getattr(cfg, "c2c_test_mode", False):
                    await self._handle_c2c_message(store, event)

        async def on_connected():
            logger.info("QQ Bot WebSocket 已连接")

        async def on_disconnected():
            logger.warning("QQ Bot WebSocket 断开")

        async def on_fatal_error(code: str, message: str):
            logger.error(f"QQ Bot 致命错误 [{code}]: {message}")

        # 会话持久化
        _session: tuple[str, int] = ("", 0)

        def get_session():
            return _session

        def set_session(session_id, seq):
            nonlocal _session
            _session = (str(session_id or ""), int(seq or 0))

        def set_heartbeat_interval(interval: float):
            pass

        def clear_token():
            pass

        def fail_pending(reason: str = ""):
            pass

        ws = QQWebSocket(
            callbacks=WSCallbacks(
                on_message_event=on_message,
                on_connected=on_connected,
                on_disconnected=on_disconnected,
                on_fatal_error=on_fatal_error,
                get_token=self._api.ensure_token_sync,
                get_session=get_session,
                set_session=set_session,
                set_heartbeat_interval=set_heartbeat_interval,
                clear_token=clear_token,
                fail_pending=fail_pending,
                get_gateway_url=self._api.get_gateway_url_sync,
            ),
        )

        gateway_url = await self._api.get_gateway_url()
        ws.start(gateway_url, asyncio.get_running_loop())
        self._ws = ws
        self._running = True
        logger.info(f"QQ Bot 已启动 (app_id={app_id[:4]}***)")
        return True

    async def stop(self):
        """停止 QQ Bot。"""
        self._running = False
        if self._ws:
            await self._ws.stop()
            self._ws = None
            logger.info("QQ Bot 已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ---- 消息处理 ----

    async def _handle_group_message(self, store: Store, event, cfg):
        """处理群 @ 消息。优先检查绑定 token，否则正常游戏流程。"""
        text = (event.content or "").strip()
        if not text:
            logger.debug("QQ群消息: 空内容，跳过")
            return

        group_id = event.chat_id
        member_openid = event.user_id

        # ---- 优先：绑定 token 检查 ----
        from core import token_bind

        logger.debug(f"绑定检查: text_len={len(text)} token_preview={token_bind.current_token(store.root)[:4]}***")
        new_token = token_bind.try_bind(store.root, text, group_id)
        if new_token is not None:
            # 绑定成功，回复确认
            try:
                await self._api.send_text(
                    event.chat_scope, group_id,
                    "✓ 群绑定成功！当前游戏目录已关联到此群。",
                    reply_to=event.message_id,
                )
            except Exception as e:
                logger.warning(f"发送绑定确认失败: {e}")
            logger.info(f"群绑定: {group_id} 已关联目录 {store.root}")
            return

        # ---- 解绑角色命令 ----
        if text in ("解绑", "解除绑定", "解绑角色"):
            result_msg = await self._handle_unbind(store, member_openid)
            try:
                await self._api.send_text(
                    event.chat_scope, group_id, result_msg,
                    reply_to=event.message_id,
                )
            except Exception as e:
                logger.warning(f"发送解绑确认失败: {e}")
            return

        # ---- 群白名单检查 ----
        bound = token_bind.bound_group(store.root)
        if bound and group_id != bound:
            return

        logger.info(f"QQ群消息: group={group_id} user={member_openid} text={text[:60]!r}")

        # 构造发送者名称
        sender_name, char_slug = self._sender_name(store, member_openid)

        # 写入统一聊天记录 + 广播 WS
        chat_msg = _db.chat_append(store.root, sender_name, text, source="qq")
        if chat_msg:
            if char_slug:
                chat_msg["character"] = char_slug
            from .routes.dispatcher import broadcast as _bc
            try:
                await _bc({"type": "broadcast_chat_msg", "payload": chat_msg})
            except Exception:
                pass

        # 构造 send_fn
        full_reply: list[str] = []

        async def _send(content: str):
            full_reply.append(content)
            chunks = _split_chunks([content])
            for i, chunk in enumerate(chunks):
                if i > 0:
                    await asyncio.sleep(0.5)
                try:
                    await self._api.send_text(event.chat_scope, event.chat_id, chunk, reply_to=event.message_id)
                except Exception as e:
                    logger.warning(f"发送QQ消息失败: {e}")

        # 调用核心处理
        try:
            input_data = TurnInput(
                store=store,
                session_key=group_id,
                member_openid=member_openid,
                group_id=group_id,
                text=text,
                send_fn=_send,
                mode="game",
            )
            logger.debug(f"process_turn 调用中: session={group_id} user={member_openid}")
            result = await process_turn(input_data)
            logger.debug(f"process_turn 完成: replied={result.replied} error={result.error}")
        except Exception as e:
            logger.exception(f"process_turn 异常: {e}")
            try:
                await self._api.send_text(
                    event.chat_scope, event.chat_id,
                    f"处理失败: {e}", reply_to=event.message_id,
                )
            except Exception:
                pass
            return

        # 写入 AI 回复 + 广播 WS
        if result.replied and full_reply:
            reply_text = "".join(full_reply)
            bot_msg = _db.chat_append(store.root, "host", reply_text, source="bot")
            if bot_msg:
                from .routes.dispatcher import broadcast as _bc
                try:
                    await _bc({"type": "broadcast_chat_msg", "payload": bot_msg})
                except Exception:
                    pass

        # 保存会话（消息粒度化存储：只存本轮增量消息）
        if result.turn_messages:
            node = _db.session_save_turn(
                store.root, result.turn_messages,
                meta={
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "sender": member_openid[:8],
                    "player_text": text[:120],
                    "reply_preview": result.reply_preview,
                    "usage": result.usage,
                    "llm_calls": result.llm_calls,
                    "total_msgs": result.total_msgs,
                },
            )
            if node:
                from .routes.dispatcher import broadcast as _bc2
                try:
                    await _bc2({
                        "type": "new_turn",
                        "payload": {
                            "id": node["id"],
                            "turn_no": node["turn_no"],
                            "sender": member_openid[:8],
                            "player_text": text[:120],
                            "reply_preview": result.reply_preview,
                            "usage": result.usage,
                            "llm_calls": result.llm_calls,
                            "total_msgs": result.total_msgs,
                            "branch_id": node["branch_id"],
                            "parent_id": node["parent_id"],
                        },
                    })
                except Exception:
                    pass

        if not result.replied:
            msg = result.error or "..."
            try:
                await self._api.send_text(event.chat_scope, event.chat_id, msg, reply_to=event.message_id)
            except Exception:
                pass

    async def _handle_c2c_message(self, store: Store, event):
        """处理 C2C 私聊消息。"""
        text = (event.content or "").strip()
        if not text:
            return

        member_openid = event.user_id
        session_key = f"c2c_{member_openid}"

        logger.info(f"QQ私聊: user={member_openid} text={text[:60]!r}")

        self._record_user_msg(store.root, store, member_openid, text, source="qq")

        full_reply: list[str] = []

        async def _send(content: str):
            full_reply.append(content)
            chunks = _split_chunks([content])
            for i, chunk in enumerate(chunks):
                if i > 0:
                    await asyncio.sleep(0.5)
                try:
                    await self._api.send_text(event.chat_scope, event.chat_id, chunk, reply_to=event.message_id)
                except Exception as e:
                    logger.warning(f"发送QQ消息失败: {e}")

        input_data = TurnInput(
            store=store,
            session_key=session_key,
            member_openid=member_openid,
            group_id=session_key,
            text=text,
            send_fn=_send,
            mode="game",
        )
        result = await process_turn(input_data)

        if result.replied and full_reply:
            self._record_bot_reply(store.root, "".join(full_reply))
        if result.turn_messages:
            self._save_session_snapshot(store.root, result, text, member_openid)
        if not result.replied:
            try:
                await self._api.send_text(event.chat_scope, event.chat_id, result.error or "...")
            except Exception:
                pass

    # ---- 辅助 ----

    def _sender_name(self, store: Store, member_openid: str) -> tuple[str, str | None]:
        """返回 (显示名, 角色slug)。"""
        char_slug = store.player_binding(member_openid)
        if char_slug and char_slug != "none":
            d = store.read("characters", char_slug)
            name = d[0].get("name", char_slug) if d else char_slug
            return (name, char_slug)
        return (f"QQ:{member_openid[:8]}", None)

    async def _handle_unbind(self, store: Store, member_openid: str) -> str:
        """解除 QQ 用户与角色的绑定。"""
        char_name = store.player_binding(member_openid) or "未知"
        store.bind_player(member_openid, "none")
        logger.info(f"解绑: qq={member_openid[:8]}... 角色={char_name}")
        return f"✓ 已解除绑定（原角色: {char_name}）。发送角色名或描述即可重新绑定。"

    def _load_bots(self):
        """读取 QQ Bot 凭据。"""
        import tomllib
        p = Path(__file__).resolve().parent.parent / "config.toml"
        if not p.exists():
            return []
        cfg = tomllib.loads(p.read_text(encoding="utf-8"))
        bots = cfg.get("qq_bots", [])
        result = []
        for b in bots:
            app_id = str(b.get("id", "")).strip()
            secret = str(b.get("secret", "")).strip()
            placeholders = {"your_app_id", "your_app_token", "your_app_secret", "123456789", ""}
            if app_id and secret and app_id not in placeholders and secret not in placeholders:
                result.append((app_id, secret))
        return result

    def _record_user_msg(self, root: Path, store: Store, member_openid: str, text: str, source: str):
        try:
            sender = self._sender_name(store, member_openid)
            _db.chat_append(root, sender, text, source=source)
        except Exception:
            pass

    def _record_bot_reply(self, root: Path, full_text: str):
        try:
            _db.chat_append(root, "host", full_text, source="bot")
        except Exception:
            pass

    def _save_session_snapshot(self, root: Path, result, text: str, member_openid: str):
        try:
            _db.session_save_turn(
                root, result.turn_messages,
                meta={
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                    "sender": member_openid[:8],
                    "player_text": text[:120],
                    "reply_preview": result.reply_preview,
                    "usage": result.usage,
                    "llm_calls": result.llm_calls,
                    "total_msgs": result.total_msgs,
                },
            )
        except Exception:
            pass


# 单例
_manager: QQBotManager | None = None


def get_qqbot() -> QQBotManager:
    global _manager
    if _manager is None:
        _manager = QQBotManager()
    return _manager
