"""types.py — 主持人核心的抽象接口层。

定义 process_turn 的输入/输出类型，以及 SendMessage 发送回调协议。
不依赖 NoneBot、QQ 事件等平台类型，是解耦的基石。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store


class SendMessage(Protocol):
    """发送消息的回调协议。

    process_turn 通过此回调发送回复文本，不关心底层实现。
    QQ 版包装 matcher.send，Web 版包装 WebSocket 推送。
    """

    async def __call__(self, content: str) -> None: ...


@dataclass
class TurnInput:
    """process_turn 的输入参数。

    封装了一次玩家消息处理所需的所有上下文。
    """

    store: Any  # store.Store 实例（运行时类型；避免 TYPE_CHECKING 导致运行时导入）
    session_key: str
    member_openid: str
    group_id: str
    text: str
    send_fn: SendMessage | None = None
    mode: str = "game"  # "game" | "create_character" | "edit"
    char_slug: str | None = None  # Web 端已知的角色 slug（跳过 player_binding 查询）


@dataclass
class TurnResult:
    """process_turn 的处理结果。

    记录本轮处理的状态，供调用方（QQ handler / Web API）检查兜底。
    """

    replied: bool = False
    reply_preview: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
