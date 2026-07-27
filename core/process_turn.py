"""process_turn.py --- 主持人核心处理逻辑（纯函数，无 NoneBot 依赖）。

从 gm.py 的 handler 中提取的纯业务逻辑，可被 QQ handler 和 Web API 共同调用。
不依赖 NoneBot / QQ 适配器 / Matcher / Event 等平台类型。

process_turn 接收类型化的 TurnInput，返回 TurnResult。
send_fn 由调用方注入——QQ 版包装 matcher.send，Web 版包装 WebSocket。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import arc, llm, store
from .types import TurnInput, TurnResult

logger = logging.getLogger(__name__)


# 单条消息最长字数（QQ 官方群文本上限约 2000，留余量按 1900 分块）。
CHUNK_SIZE = 1900
# 工具调用循环最大轮数，防止模型失控无限调工具。
MAX_TOOL_ROUNDS = 20


# ---------------------------------------------------------------------------
# 工具上下文
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """单次消息处理内的可变状态与外部依赖。

    每个 @bot 消息新建一个。工具实现通过它访问 store / 群信息 / 发送回调。
    """

    store: store.Store
    member_openid: str
    group_id: str
    raw_text: str
    send_fn: Callable[[str], Awaitable[None]] | None = None
    replied: bool = False
    reply_preview: str = ""
    last_usage: dict[str, int] = field(default_factory=dict)


# ===========================================================================
# 上下文加载
# ===========================================================================

def _load_runtime_prompt(mode: str = "game") -> str:
    """加载运行时提示词。mode 决定用 GM 提示词还是编辑助手提示词。"""
    filename = "editor_runtime.md" if mode == "edit" else "gm_runtime.md"
    # 从 core/ 目录读取提示词文件
    p = Path(__file__).resolve().parent / filename
    return p.read_text(encoding="utf-8")


def _load_system_prefix(s: store.Store, mode: str = "game") -> str:
    """构造稳定 system 前缀：运行时提示词 + 世界书 + 文风参考。

    这几部分每轮不变，作为消息列表首条，让 DeepSeek 等提供商的前缀缓存命中。
    editor 模式不加世界书（编辑助手不需要常驻世界观知识）。
    """
    runtime = _load_runtime_prompt(mode)
    parts = [runtime]
    if mode != "edit":
        # 编辑助手不加载世界书——它面向备团用户，不需要跑团世界观上下文
        world = s.read_world_book()
        if world:
            parts.append(f"---\n\n# 世界书（常驻世界观知识，你的设定依据）\n\n{world}")
        style = s.read_style_guide()
        if style:
            parts.append(f"---\n\n# 文风参考（叙事调性，演绎 NPC 台词与场景描写时模仿此风格）\n\n{style}")
    return "\n\n".join(parts)


def _build_sender_frame(s: store.Store, group_id: str, member_openid: str, char_slug: str | None = None) -> str:
    """构造发送人框架：最小必要信息（谁在说话、关联角色、绑定状态）。
    
    char_slug: Web 端已知的角色 slug（优先级高于 player_binding 查询）。
    """
    effective_slug = char_slug or s.player_binding(member_openid)

    if effective_slug:
        d = s.read("characters", effective_slug)
        char_name = d[0].get("name", effective_slug) if d else effective_slug
        char_identity = d[0].get("identity", "") if d else ""
        scene_slug = s.char_scene(group_id, effective_slug)
        scene_name = ""
        if scene_slug:
            sd = s.read("scenes", scene_slug)
            scene_name = sd[0].get("name", scene_slug) if sd else scene_slug
        loc = f" | 当前场景: {scene_name}" if scene_name else ""
        ident = f"（{char_identity}）" if char_identity else ""
        return f'<turn sender="{char_name}" char="{effective_slug}"{loc}>\n状态: 已绑定角色{ident}'
    else:
        pending = _find_pending_char(s, member_openid)
        if pending:
            pd = s.read("characters", pending)
            pname = pd[0].get("name", pending) if pd else pending
            return (
                f'<turn sender="未绑定玩家" pending_char="{pending}">\n'
                f'状态: 有待确认角色卡「{pname}」，若玩家确认则 finalize_character'
            )
        return '<turn sender="未绑定玩家">\n状态: 尚未绑定角色，若为概括叙述则走角色创建'


def _find_pending_char(s: store.Store, member_openid: str) -> str | None:
    """查找某玩家的待确认角色草案 slug。"""
    for d in s.list_docs("characters"):
        if d["meta"].get("status") == "待确认" and d["meta"].get("owner_openid") == member_openid:
            return d["slug"]
    return None


# ===========================================================================
# 消息分块
# ===========================================================================

def _split_chunks(replies: list[str]) -> list[str]:
    """把多条回复合并后按 CHUNK_SIZE 切分。"""
    if not any(r and r.strip() for r in replies):
        return []
    out: list[str] = []
    for r in replies:
        r = r.strip()
        if not r:
            continue
        while len(r) > CHUNK_SIZE:
            out.append(r[:CHUNK_SIZE])
            r = r[CHUNK_SIZE:]
        if r:
            out.append(r)
    return out


# ===========================================================================
# 核心处理函数
# ===========================================================================

async def process_turn(input: TurnInput) -> TurnResult:
    """处理一次玩家消息的主循环。

    这是原来 gm.py:handle_group_at 的核心逻辑的纯函数版本。
    不依赖 NoneBot 类型，send_fn 由调用方注入。

    流程：
      1. 加载历史
      2. 构造 system 前缀 + 发送人框架
      3. 工具调用循环（最多 MAX_TOOL_ROUNDS 轮）
      4. 保存历史快照
      5. 返回处理结果
    """
    # 延迟导入 --- dispatch/tool_schemas 在 tools.py 中定义，依赖其 @tool 装饰器
    # 注册的工具表。process_turn 本身不直接引用 NoneBot 类型。
    from .tools import dispatch, tool_schemas

    s = input.store
    result = TurnResult()

    # ── 加载对话历史 ──
    session_key = input.session_key
    history = s.load_history(session_key)

    # ── 构造 system 前缀（每轮刷新，世界书可能更新）──
    system_prefix = _load_system_prefix(s, input.mode)

    # ── 发送人框架 ──
    sender_frame = _build_sender_frame(s, input.group_id, input.member_openid, input.char_slug)
    turn_user = f"{sender_frame}\n\n{input.text}\n</turn>"

    # ── 构造本轮 messages ──
    history_body = [m for m in history if m.get("role") != "system"]
    if history_body:
        reply_hint = "\n\n（处理完后必须调用 reply 工具发送回复。）"
        messages = [{"role": "system", "content": system_prefix}] + history_body + [{"role": "user", "content": turn_user + reply_hint}]
    else:
        reply_hint = (
            "\n\n（首次对话。如需了解当前场景/在场者/已有弧光，"
            "用 query_locations / query_memory 工具查询。处理完后**必须调用 reply 工具发送回复**。）"
        )
        messages = [
            {"role": "system", "content": system_prefix},
            {"role": "user", "content": turn_user + reply_hint},
        ]

    # ── 工具上下文 ──
    ctx = ToolContext(
        store=s,
        member_openid=input.member_openid,
        group_id=input.group_id,
        raw_text=input.text,
        send_fn=input.send_fn,
    )

    # ── 工具调用循环（流式：reply 工具被调用时立即发送）──
    schemas = tool_schemas()
    logger.info(f"准备调用 LLM: model={llm.config().model} messages={len(messages)} tools={len(schemas)}")
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            assistant = await llm.chat_with_tools(messages, schemas)
        except Exception as e:
            logger.exception("LLM 调用失败")
            if not ctx.replied:
                result.error = "LLM 调用失败"
            break

        # 累加 token 用量
        u = assistant.usage
        if u:
            ctx.last_usage = {
                "prompt_tokens": ctx.last_usage.get("prompt_tokens", 0) + u.get("prompt_tokens", 0),
                "completion_tokens": ctx.last_usage.get("completion_tokens", 0) + u.get("completion_tokens", 0),
                "cached_tokens": ctx.last_usage.get("cached_tokens", 0) + u.get("cached_tokens", 0),
            }
            logger.info(
                f"LLM 用量(本轮累计): prompt={ctx.last_usage['prompt_tokens']} "
                f"cached={ctx.last_usage['cached_tokens']}/{ctx.last_usage['prompt_tokens']} "
                f"completion={ctx.last_usage['completion_tokens']}"
            )

        messages.append(llm.assistant_to_message(assistant))

        if not assistant.has_tool_calls:
            if not ctx.replied:
                # 模型停止但没调 reply → 不丢弃，留给后续重试机制
                if assistant.content.strip():
                    logger.warning(
                        f"LLM 未调 reply 即停止，content 待重试 "
                        f"({len(assistant.content)}chars): {assistant.content[:80]!r}"
                    )
            elif assistant.content.strip():
                logger.warning(f"LLM reply 后又生成残留文本，已丢弃：{assistant.content[:80]!r}")
            break

        # 执行工具调用
        for call in assistant.tool_calls:
            tool_result = await dispatch(ctx, call)
            messages.append(llm.tool_result_message(call.id, tool_result))
    else:
        # 触达 MAX_TOOL_ROUNDS 仍未收尾
        if not ctx.replied:
            result.error = "工具调用循环达到上限，强制收尾"
        logger.warning("工具调用循环达到上限，强制收尾")

    # ── 重试：若本轮从未调 reply，注入提示让 AI 补刀 ──
    if not ctx.replied:
        retry_prompt = (
            "（系统提示：你本轮尚未调用 reply 工具回复玩家。"
            "请调用 reply(content=\"...\") 将你的回复内容发送给玩家。）"
        )
        messages.append({"role": "user", "content": retry_prompt})
        logger.info(f"注入 reply 重试提示，messages={len(messages)}")

        for _ in range(2):  # 重试最多 2 轮
            try:
                assistant = await llm.chat_with_tools(messages, schemas)
            except Exception:
                logger.exception("重试轮 LLM 调用失败")
                break

            u = assistant.usage
            if u:
                ctx.last_usage["prompt_tokens"] = ctx.last_usage.get("prompt_tokens", 0) + u.get("prompt_tokens", 0)
                ctx.last_usage["completion_tokens"] = ctx.last_usage.get("completion_tokens", 0) + u.get("completion_tokens", 0)
                ctx.last_usage["cached_tokens"] = ctx.last_usage.get("cached_tokens", 0) + u.get("cached_tokens", 0)

            messages.append(llm.assistant_to_message(assistant))

            if not assistant.has_tool_calls:
                break

            for call in assistant.tool_calls:
                tool_result = await dispatch(ctx, call)
                messages.append(llm.tool_result_message(call.id, tool_result))

            if ctx.replied:
                logger.info("重试成功：reply 已被调用")
                break
        else:
            logger.warning("重试轮达到上限")

        # 重试后仍未调 reply → 发送固定提示
        if not ctx.replied and ctx.send_fn:
            await ctx.send_fn("（AI 未生成回复，请重试）")
            ctx.replied = True
            ctx.reply_preview = "（AI 未生成回复，请重试）"
            logger.warning("重试后 LLM 仍拒绝调 reply，已发送固定提示")

    # ── 提取发送人名用于快照 meta ──
    sender_name = ""
    _sf = sender_frame
    if 'sender="' in _sf:
        sender_name = _sf.split('sender="', 1)[1].split('"', 1)[0]

    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender_name,
        "player_text": input.text[:120],
        "reply_preview": ctx.reply_preview,
        "usage": ctx.last_usage,
    }

    # ── 填充结果 ──
    result.replied = ctx.replied
    result.reply_preview = ctx.reply_preview
    result.usage = ctx.last_usage
    result.messages = messages

    return result
