"""process_turn.py --- 主持人核心处理逻辑（纯函数，无 NoneBot 依赖）。

从 gm.py 的 handler 中提取的纯业务逻辑，可被 QQ handler 和 Web API 共同调用。
不依赖 NoneBot / QQ 适配器 / Matcher / Event 等平台类型。

process_turn 接收类型化的 TurnInput，返回 TurnResult。
send_fn 由调用方注入——QQ 版包装 matcher.send，Web 版包装 WebSocket。
"""

from __future__ import annotations

import json
import logging
import re
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
# Tool Output Folding: 旧 tool output 超过此轮次差 → 折叠为标记。
TOOL_OUTPUT_FOLD_MIN_AGE = 3
# Tool Output Folding: content 短于此长度的 tool output 不折叠（节省无意义）。
TOOL_OUTPUT_FOLD_MIN_SIZE = 500


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
    outbox: str = ""  # 待发送文档（内存）：LLM 经 outbox_append/outbox_rewrite 写入，turn 结束清理阶段统一发送
    replied: bool = False
    reply_preview: str = ""
    last_usage: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 待发送文档（outbox）与轮次号
# ---------------------------------------------------------------------------

def _compute_turn_no(s: store.Store) -> int:
    """计算下一轮次号：tree_nodes 表 MAX(turn_no) + 1。"""
    from .db import _session_db
    import sqlite3 as _sqlite3

    _sdb = _session_db(s.root)
    if _sdb.exists():
        try:
            with _sqlite3.connect(str(_sdb)) as _conn:
                _row = _conn.execute("SELECT MAX(turn_no) FROM tree_nodes").fetchone()
            return (_row[0] or 0) + 1
        except Exception:
            return 1
    return 1


def _dump_outbox(ctx: ToolContext, s: store.Store, turn_no: int) -> None:
    """turn 出问题时把待发送文档落盘（.atrpg/outbox/turn_<no>.md），防止草稿丢失。"""
    if not ctx.outbox.strip():
        return
    try:
        out_dir = s.root / ".atrpg" / "outbox"
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"turn_{turn_no:05d}.md"
        p.write_text(ctx.outbox.strip(), encoding="utf-8")
        logger.warning(f"待发送文档已落盘（turn 异常）: {p} ({len(ctx.outbox)}字)")
    except Exception:
        logger.exception("待发送文档落盘失败")


# ===========================================================================
# 上下文加载
# ===========================================================================

def _load_runtime_prompt(mode: str = "game") -> str:
    """加载运行时提示词。mode 决定用 GM 提示词还是编辑助手提示词。"""
    filename = "editor_runtime.md" if mode == "edit" else "gm_runtime.md"
    # 从 core/ 目录读取提示词文件
    p = Path(__file__).resolve().parent / filename
    return p.read_text(encoding="utf-8")


# system prefix 缓存：(game_dir, mode) → (mtime_key, content)
_system_prefix_cache: dict[tuple[str, str], tuple[float, str]] = {}


def _load_system_prefix(s: store.Store, mode: str = "game") -> str:
    """构造稳定 system 前缀：运行时提示词 + 世界书 + 文风参考。

    这几部分每轮不变，作为消息列表首条，让 DeepSeek 等提供商的前缀缓存命中。
    editor 模式不加世界书（编辑助手不需要常驻世界观知识）。

    结果以文件 mtime 为 key 缓存，只有文件变动时才重新生成。
    """
    game_dir = str(s.root)
    cache_key = (game_dir, mode)

    # 计算各来源文件的 mtime 作为缓存版本
    runtime_file = (
        Path(__file__).resolve().parent / ("editor_runtime.md" if mode == "edit" else "gm_runtime.md")
    )
    world_file = s.root / "data" / "world-book.md"
    style_file = s.root / "data" / "style-guide.md"

    mtime_key = runtime_file.stat().st_mtime if runtime_file.exists() else 0
    if mode != "edit":
        if world_file.exists():
            mtime_key += world_file.stat().st_mtime
        if style_file.exists():
            mtime_key += style_file.stat().st_mtime

    cached = _system_prefix_cache.get(cache_key)
    if cached and cached[0] == mtime_key:
        return cached[1]

    runtime = _load_runtime_prompt(mode)
    parts = [runtime]
    if mode != "edit":
        world = s.read_world_book()
        if world:
            parts.append(f"---\n\n# 世界书（常驻世界观知识，你的设定依据）\n\n{world}")
        style = s.read_style_guide()
        if style:
            parts.append(f"---\n\n# 文风参考（叙事调性，演绎 NPC 台词与情景描写时模仿此风格）\n\n{style}")
    result = "\n\n".join(parts)
    _system_prefix_cache[cache_key] = (mtime_key, result)
    return result


def _build_sender_frame(s: store.Store, group_id: str, member_openid: str, char_slug: str | None = None) -> str:
    """构造发送人框架：角色名、情景、同场角色/NPC、地点。

    char_slug: Web 端已知的角色 slug（优先级高于 player_binding 查询）。
    """
    effective_slug = char_slug or s.player_binding(member_openid)

    if effective_slug:
        d = s.read("characters", effective_slug)
        char_name = d[0].get("name", effective_slug) if d else effective_slug
        char_identity = d[0].get("identity", "") if d else ""

        scene_slug = s.char_current_scene(effective_slug) or s.char_scene(group_id, effective_slug)
        scene_name = ""
        location_str = ""
        present_parts: list[str] = []

        if scene_slug:
            sd = s.read("scenes", scene_slug)
            scene_name = sd[0].get("name", scene_slug) if sd else scene_slug

            # 同场角色 + NPC
            chars, npcs = s.who_in_scene(scene_slug)
            other_chars = [c for c in chars if c != effective_slug]
            if other_chars:
                cn = []
                for c in other_chars:
                    cd = s.read("characters", c)
                    cn.append(cd[0].get("name", c) if cd else c)
                present_parts.append(f"同场角色: {', '.join(cn)}")
            if npcs:
                nn = []
                for n in npcs:
                    nd = s.read("npcs", n)
                    nn.append(nd[0].get("name", n) if nd else n)
                present_parts.append(f"同场NPC: {', '.join(nn)}")

            # 所属地点 + 缺失提示
            hints: list[str] = []
            if sd:
                loc_slug = sd[0].get("location")
                if loc_slug:
                    loc_name = s.location_name(loc_slug)
                    if loc_name:
                        location_str = f" | 地点: {loc_name}"
                    else:
                        hints.append(f"⚠ 地点 {loc_slug} 不存在，可 create_location")
            else:
                hints.append(f"⚠ 情景 {scene_slug} 档案缺失，可 create_scene")
            if hints:
                present_parts.extend(hints)

        loc = f" | 情景: {scene_name}" if scene_name else ""
        present = ("\n" + " | ".join(present_parts)) if present_parts else ""
        ident = f"（{char_identity}）" if char_identity else ""
        return f'<turn sender="{char_name}" char="{effective_slug}"{loc}{location_str}>{present}\n状态: 已绑定角色{ident}\n（需要情景详情时调用 query_character_scene 工具）'
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
# Tool Output Folding
# ===========================================================================

def _fold_old_tool_outputs(messages: list[dict[str, Any]], current_turn: int) -> None:
    """折叠旧的 tool output：超过阈值的内容替换为 (内容已折叠)。

    依赖 tool_result_message 写入的 HTML 注释 <!-- turn:N --> 判断轮次。
    无标记的旧消息（legacy）跳过不处理。
    对 messages 原地修改。
    """
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content: str = msg.get("content", "")
        if len(content) <= TOOL_OUTPUT_FOLD_MIN_SIZE:
            continue
        m = re.search(r'<!-- turn:(\d+) -->', content)
        if not m:
            continue  # legacy 消息无轮次标记，跳过
        msg_turn = int(m.group(1))
        age = current_turn - msg_turn
        if age > TOOL_OUTPUT_FOLD_MIN_AGE:
            msg["content"] = "(内容已折叠)"


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
      4. 清理阶段：发送待发送文档（outbox）
      5. 保存历史快照
      6. 返回处理结果

    turn 中出问题（未捕获异常）时，若 outbox 已有内容则落盘 .atrpg/outbox/ 防止草稿丢失。
    """
    ctx = ToolContext(
        store=input.store,
        member_openid=input.member_openid,
        group_id=input.group_id,
        raw_text=input.text,
        send_fn=input.send_fn,
    )
    try:
        return await _process_turn_impl(input, ctx)
    except BaseException:
        # turn 中出问题：待发送文档草稿落盘防止丢失，再抛给调用方（QQ/WS/GM）
        _dump_outbox(ctx, input.store, _compute_turn_no(input.store))
        raise


async def _process_turn_impl(input: TurnInput, ctx: ToolContext) -> TurnResult:
    """process_turn 的主体实现。

    ctx 携带本轮可变状态（含 outbox 草稿）；未捕获异常由 process_turn 外层落盘。
    """
    # 延迟导入 --- dispatch/tool_schemas 在 tools.py 中定义，依赖其 @tool 装饰器
    # 注册的工具表。process_turn 本身不直接引用 NoneBot 类型。
    from .tools import dispatch, tool_schemas

    s = input.store
    result = TurnResult()

    # ── 加载对话历史 ──
    session_key = input.session_key
    history = s.load_history(session_key)
    logger.info(
        f"加载历史: session={session_key} history_len={len(history)} "
        f"has_body={bool([m for m in history if m.get('role') != 'system'])}"
    )

    # ── 计算当前轮次号（用于 Tool Output Folding 标记）──
    # 消息粒度化存储后，轮次号取自 tree_nodes 表
    turn_no = _compute_turn_no(s)

    # ── 构造 system 前缀（每轮刷新，世界书可能更新）──
    system_prefix = _load_system_prefix(s, input.mode)

    # ── 发送人框架 ──
    sender_frame = _build_sender_frame(s, input.group_id, input.member_openid, input.char_slug)
    turn_user = f"{sender_frame}\n\n{input.text}\n</turn>"

    # ── 构造本轮 messages ──
    history_body = [m for m in history if m.get("role") != "system"]
    reply_hint = "\n\n（处理完后必须调用 outbox_append 工具，把要发给玩家的内容写入待发送文档，turn 结束时自动发送。）"
    if history_body:
        messages = [{"role": "system", "content": system_prefix}] + history_body + [{"role": "user", "content": turn_user + reply_hint}]
    else:
        reply_hint = (
            "\n\n（首次对话。如需了解当前情景/在场者/已有弧光，"
            "用 query_character_scene / query_memory 工具查询。处理完后**必须调用 outbox_append 工具**把回复写入待发送文档，turn 结束时自动发送。）"
        )
        messages = [
            {"role": "system", "content": system_prefix},
            {"role": "user", "content": turn_user + reply_hint},
        ]

    # ── 记录本轮 user 消息在 messages 中的位置（用于提取增量）──
    turn_user_idx = len(messages) - 1  # turn_user 总是在 messages 末尾

    # 工具上下文（含 outbox 待发送文档）由 process_turn 外层创建

    # ── 工具调用循环（内容写入 outbox，清理阶段统一发送）──
    schemas = tool_schemas()
    llm_call_count = 0

    # ── Tool Output Folding: 每轮 LLM 调用前折叠旧的 tool output ──
    _fold_old_tool_outputs(messages, turn_no)

    logger.info(f"准备调用 LLM: model={llm.resolve_profile('chat').model} messages={len(messages)} tools={len(schemas)}")
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            assistant = await llm.chat_with_tools(messages, schemas)
        except Exception as e:
            logger.exception("LLM 调用失败")
            if not ctx.outbox.strip():
                result.error = "LLM 调用失败"
            else:
                # 文档已有内容：落盘备份，清理阶段仍会发送
                _dump_outbox(ctx, s, turn_no)
            break

        llm_call_count += 1

        # 累加 token 用量
        u = assistant.usage
        if u:
            ctx.last_usage = {
                "prompt_tokens": ctx.last_usage.get("prompt_tokens", 0) + u.get("prompt_tokens", 0),
                "completion_tokens": ctx.last_usage.get("completion_tokens", 0) + u.get("completion_tokens", 0),
                "cached_tokens": ctx.last_usage.get("cached_tokens", 0) + u.get("cached_tokens", 0),
            }
            _p = ctx.last_usage['prompt_tokens']
            _c = ctx.last_usage['cached_tokens']
            _o = ctx.last_usage['completion_tokens']
            logger.info(
                f"LLM call#{llm_call_count}: prompt={_p} "
                f"cached={_c}/{_p} completion={_o}"
            )

        messages.append(llm.assistant_to_message(assistant))

        if not assistant.has_tool_calls:
            if not ctx.outbox.strip():
                # 模型停止但文档为空 → 不丢弃 content，留给后续重试机制
                if assistant.content.strip():
                    logger.warning(
                        f"LLM 未写文档即停止，content 待重试 "
                        f"({len(assistant.content)}chars): {assistant.content[:80]!r}"
                    )
            elif assistant.content.strip():
                logger.warning(f"LLM 写文档后又生成残留文本，已丢弃：{assistant.content[:80]!r}")
            break

        # 执行工具调用
        for call in assistant.tool_calls:
            tool_result = await dispatch(ctx, call)
            messages.append(llm.tool_result_message(call.id, tool_result, turn_no=turn_no))
    else:
        # 触达 MAX_TOOL_ROUNDS 仍未收尾
        if not ctx.outbox.strip():
            result.error = "工具调用循环达到上限，强制收尾"
        else:
            _dump_outbox(ctx, s, turn_no)
        logger.warning("工具调用循环达到上限，强制收尾")

    # ── 重试：若文档仍为空，注入提示让 AI 补刀 ──
    if not ctx.outbox.strip():
        retry_prompt = "请调用 outbox_append 工具，把要发给玩家的故事内容写入待发送文档。"
        messages.append({"role": "user", "content": retry_prompt})
        logger.info(f"注入 outbox 重试提示，messages={len(messages)}")

        for _ in range(2):  # 重试最多 2 轮
            try:
                assistant = await llm.chat_with_tools(messages, schemas)
            except Exception:
                logger.exception("重试轮 LLM 调用失败")
                if ctx.outbox.strip():
                    _dump_outbox(ctx, s, turn_no)
                break

            llm_call_count += 1

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
                messages.append(llm.tool_result_message(call.id, tool_result, turn_no=turn_no))

            if ctx.outbox.strip():
                logger.info("重试成功：outbox 已被写入")
                break
        else:
            logger.warning("重试轮达到上限")

    # ── 清理阶段：发送待发送文档（原 reply 即时发送改为统一发送）──
    if ctx.outbox.strip():
        outbox_text = ctx.outbox.strip()
        if ctx.send_fn:
            for chunk in _split_chunks([outbox_text]):
                await ctx.send_fn(chunk)
        ctx.replied = True
        ctx.reply_preview = outbox_text[:120]
    elif ctx.send_fn:
        # 兜底：文档为空 → 发送固定提示
        await ctx.send_fn("（AI 未生成回复，请重试）")
        ctx.replied = True
        ctx.reply_preview = "（AI 未生成回复，请重试）"
        logger.warning("turn 结束待发送文档仍为空，已发送固定提示")

    # 防御：出错路径（LLM 异常/循环上限）若文档有内容，此处兜底落盘
    if result.error and ctx.outbox.strip():
        _dump_outbox(ctx, s, turn_no)

    # ── 计算本轮增量消息用于快照（不含 system 前缀）──
    stored_messages = messages[1:]  # 剥离 system，只存对话部分
    turn_delta = stored_messages[turn_user_idx - 1:]  # turn_user_idx 含 system，减 1 对齐

    ctx_msgs = len(stored_messages)
    logger.info(
        f"快照准备: total_msgs={len(messages)} stored={ctx_msgs} "
        f"turn_user_idx={turn_user_idx} delta={len(turn_delta)} "
        f"delta_roles={[m['role'] for m in turn_delta[:3]]}"
    )

    # ── 本轮结束 token 汇总日志 ──
    _u = ctx.last_usage
    _p = _u.get("prompt_tokens", 0)
    _c = _u.get("cached_tokens", 0)
    _o = _u.get("completion_tokens", 0)
    _m = _p - _c  # 未命中缓存
    _t = _p + _o  # 总计
    logger.info(
        f"LLM 本轮结束: calls={llm_call_count} ctx_msgs={ctx_msgs} "
        f"总计:{_t}(命中:{_c}/未命中:{_m}/输入:{_p}/输出:{_o})"
    )

    # ── 填充结果 ──
    result.replied = ctx.replied
    result.reply_preview = ctx.reply_preview
    result.usage = ctx.last_usage
    result.messages = stored_messages
    result.turn_messages = turn_delta
    result.llm_calls = llm_call_count
    result.total_msgs = ctx_msgs

    return result
