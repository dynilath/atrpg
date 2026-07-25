"""gm.py — QQ 机器人入口。

工具注册表已提取到 tools.py（纯逻辑，零平台依赖）。
本文件仅负责 QQ 适配层：matcher + send_fn 包装。
"""

from __future__ import annotations

from nonebot import get_driver, logger, on_message
from nonebot.adapters.qq import Bot, C2CMessageCreateEvent, GroupAtMessageCreateEvent
from nonebot.matcher import Matcher
from nonebot.rule import is_type

from . import store
from .process_turn import process_turn, _split_chunks
from .types import TurnInput

# 导入 tools 以触发工具注册（副作用：@tool 装饰器填充 _REGISTRY）
from . import tools  # noqa: F401


def get_store() -> store.Store:
    """从 NoneBot 配置读取游戏目录，构造 Store。"""
    game_dir = get_driver().config.atrpg_game_dir
    return store.Store(game_dir)


# ===========================================================================
# matcher 入口
# ===========================================================================

group_at = on_message(
    rule=is_type(GroupAtMessageCreateEvent, C2CMessageCreateEvent),
    priority=10,
    block=True,
)


def _resolve_session(event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> tuple[str, str, bool]:
    if isinstance(event, C2CMessageCreateEvent):
        return event.author.user_openid, f"c2c_{event.author.user_openid}", True
    return event.author.member_openid, event.group_openid, False


@group_at.handle()
async def handle_group_at(bot: Bot, matcher: Matcher, event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> None:
    member_openid, group_id, is_c2c = _resolve_session(event)
    text = event.get_plaintext().strip()

    if not text:
        return

    if is_c2c and not getattr(get_driver().config, "atrpg_c2c_test_mode", False):
        return

    try:
        s = get_store()
    except store.StoreError as e:
        await matcher.send(f"⚠ 游戏目录未就绪：{e}")
        return

    if not is_c2c:
        target_group = str(getattr(get_driver().config, "atrpg_target_group", "")).strip()
        if target_group and group_id != target_group:
            return

    logger.info(f"GM 处理: {'c2c' if is_c2c else 'group'}={group_id} member={member_openid} text={text[:40]!r}")

    async def _send(content: str) -> None:
        import asyncio
        chunks = _split_chunks([content])
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(0.5)
            try:
                await matcher.send(chunk)
            except Exception as e:
                logger.warning(f"发送消息到群失败（可能去重）：{e}")

    input_data = TurnInput(
        store=s, session_key=group_id, member_openid=member_openid,
        group_id=group_id, text=text, send_fn=_send,
    )
    result = await process_turn(input_data)

    if not result.replied:
        msg = result.error or "（主持人已处理，但没有产生回复内容。）"
        await matcher.send(msg)
