"""gm.py — 主持人核心调度。

收到 QQ 群 @bot 消息后，按「加载上下文 → 工具调用循环 → 分块回群」处理。
所有判断交给 LLM 主持人（见 gm_runtime.md），Python 只负责：
  1. 把玩家文本 + 游戏上下文喂给 LLM；
  2. 把 store/arc 的接口包装成工具，供 LLM 通过 tool call 表达落盘意图；
  3. 执行工具调用，把结果回灌给 LLM，直到它收尾（调用 reply 并无更多工具）；
  4. 把收集到的回复文本分块发回群里。

不搞命令分发器：只有一个 matcher 入口，所有玩家文本自由进入。
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from nonebot import get_driver, logger, on_message
from nonebot.adapters.qq import Bot, GroupAtMessageCreateEvent
from nonebot.matcher import Matcher
from nonebot.rule import is_type

from . import arc, llm, store

# 单条消息最长字数（QQ 官方群文本上限约 2000，留余量按 1900 分块）。
CHUNK_SIZE = 1900
# 工具调用循环最大轮数，防止模型失控无限调工具。
MAX_TOOL_ROUNDS = 6


# ---------------------------------------------------------------------------
# 工具上下文
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """单次消息处理内的可变状态与外部依赖。

    每个 @bot 消息新建一个。工具实现通过它访问 store / 群信息 / 草案。
    """

    store: store.Store
    member_openid: str
    group_id: str
    # 玩家本轮发送的原始文本
    raw_text: str
    # 草案暂存：draft_token → 草案 dict（draft_character 生成，finalize_character 消费）
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 收集本轮要发群的回复文本（reply 工具写入，handler 末尾分块发送）
    replies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """一个工具的定义：JSON schema + 实现。

    实现签名为 async def(ctx: ToolContext, **kwargs) -> str
    返回值作为 tool result 回灌给 LLM（让模型知道动作生效了）。
    """

    schema: dict[str, Any]
    func: Callable[..., Awaitable[str]]


_REGISTRY: dict[str, ToolDef] = {}


def tool(name: str, description: str, params: dict[str, Any]):
    """工具注册装饰器。

    用法：
        @tool("reply", "向玩家发消息", {"type": "object", "properties": {...}, ...})
        async def reply(ctx: ToolContext, content: str) -> str: ...
    会自动包成 OpenAI function schema 并注册。
    """

    def deco(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": params,
            },
        }
        _REGISTRY[name] = ToolDef(schema=schema, func=func)
        return func

    return deco


def tool_schemas() -> list[dict[str, Any]]:
    """所有工具的 OpenAI schema 列表（传给 llm.chat_with_tools 的 tools 参数）。"""
    return [td.schema for td in _REGISTRY.values()]


async def dispatch(ctx: ToolContext, call: llm.ToolCall) -> str:
    """执行一次工具调用，返回结果字符串（失败时返回错误说明，不抛异常中断循环）。"""
    td = _REGISTRY.get(call.name)
    if td is None:
        return f"错误：未知工具 '{call.name}'"
    try:
        return await td.func(ctx, **call.arguments)
    except (arc.ArcError, store.StoreError) as e:
        # 业务越权/校验错误：反馈给 LLM，让它改用合规做法
        return f"错误：{e}"
    except Exception as e:  # noqa: BLE001 — 工具循环不能因单个工具崩溃中断
        logger.opt(exception=e).warning(f"工具 {call.name} 执行异常")
        return f"错误：执行 {call.name} 时发生内部错误：{e}"


# ===========================================================================
# 工具实现
# ===========================================================================

# --- 回复工具 ---------------------------------------------------------------

@tool(
    "reply",
    "向玩家发送消息（演绎文本、NPC 台词、裁决结果、场景描写、给玩家的提示/选项）。"
    "这是把内容发到 QQ 群的唯一出口。可多次调用以分段发送。",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要发给玩家的文本内容"},
        },
        "required": ["content"],
    },
)
async def reply(ctx: ToolContext, content: str) -> str:
    ctx.replies.append(content)
    return "已加入待发送回复队列。"


# --- 角色与场景工具 ---------------------------------------------------------

@tool(
    "draft_character",
    "当玩家给出概括叙述（如「我是个流浪剑客，在找失散的妹妹」）且尚未绑定角色时，"
    "生成完整角色卡草案。草案先发给玩家确认/修改，确认后才正式落盘。"
    "本工具不落盘，只返回草案。请基于玩家叙述补全外貌/性格/能力/背景，"
    "动机尽量挂接到已有主要弧光。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "角色姓名"},
            "identity": {"type": "string", "description": "身份，如 流浪剑客 / 港口守卫"},
            "appearance": {"type": "string", "description": "外貌描写（2-4 句）"},
            "personality": {"type": "string", "description": "性格关键词与简述"},
            "background": {"type": "string", "description": "出身、经历、为何在此"},
            "skills": {"type": "string", "description": "核心技能与熟练度、属性倾向"},
            "hooks": {"type": "string", "description": "剧情连接：卷入哪条弧光、当前目标"},
        },
        "required": ["name", "identity", "background"],
    },
)
async def draft_character(
    ctx: ToolContext,
    name: str,
    identity: str,
    background: str,
    appearance: str = "",
    personality: str = "",
    skills: str = "",
    hooks: str = "",
) -> str:
    # 若该玩家已绑定角色，不允许再建草案
    if ctx.store.player_binding(ctx.member_openid):
        return "错误：该玩家已绑定角色，不能再次创建。请用行动处理。"

    draft = {
        "name": name,
        "identity": identity,
        "appearance": appearance,
        "personality": personality,
        "background": background,
        "skills": skills,
        "hooks": hooks,
        "slug": store.slugify(name),
    }
    token = secrets.token_hex(4)
    ctx.drafts[token] = draft

    # 把草案展示给玩家，请求确认
    card = _render_draft_card(draft)
    ctx.replies.append(card)
    return (
        f"已生成角色卡草案（draft_token={token}），已展示给玩家。"
        "等待玩家回复确认（如「确认」「就这样」）后，调用 finalize_character 落盘。"
    )


@tool(
    "finalize_character",
    "玩家确认角色卡草案后，正式落盘：创建角色档案、绑定 QQ↔角色、"
    "把角色放入指定场景的在场者并记录场景归属。必须先用 draft_character 生成草案。",
    {
        "type": "object",
        "properties": {
            "draft_token": {"type": "string", "description": "draft_character 返回的 token"},
            "scene_slug": {
                "type": "string",
                "description": "初始场景 slug（由你决定，不由玩家选）",
            },
        },
        "required": ["draft_token", "scene_slug"],
    },
)
async def finalize_character(ctx: ToolContext, draft_token: str, scene_slug: str) -> str:
    draft = ctx.drafts.get(draft_token)
    if draft is None:
        return f"错误：draft_token '{draft_token}' 无效或已过期。请重新 draft_character。"

    # 校验场景存在
    scene = ctx.store.read("scenes", scene_slug)
    if scene is None:
        return f"错误：场景 '{scene_slug}' 不存在。请用 query_memory 查可用场景或 create_scene 新建。"

    slug = draft["slug"]
    meta, body = scene
    # 角色档案
    char_body = _render_character_body(draft)
    ctx.store.write(
        "characters",
        slug,
        {
            "姓名": draft["name"],
            "类型": "玩家角色",
            "身份": draft["identity"],
            "slug": slug,
        },
        char_body,
    )
    # 绑定 QQ↔角色
    ctx.store.bind_player(ctx.member_openid, slug, draft["name"])
    # 场景归属 + 在场者追加
    ctx.store.set_char_scene(ctx.group_id, slug, scene_slug)
    _append_attendee(ctx.store, scene_slug, slug)
    # 通知系统：维护轮次提示
    ctx.replies.append(
        f"✓ 角色档案已落盘：data/characters/{slug}.md\n"
        f"✓ 已绑定 QQ↔角色，初始场景：{meta.get('名称', scene_slug)}"
    )
    # 草案消费后清除
    ctx.drafts.pop(draft_token, None)
    return f"角色 {draft['name']}（{slug}）已正式落盘并绑定，初始场景 {scene_slug}。"


@tool(
    "append_scene_dialogue",
    "向某场景的「对话与行动记录」追加一轮（玩家行动 + 你的裁决 + NPC 反应 + 环境推进）。"
    "每次玩家行动裁决后都应调用，以保证剧情持久化。",
    {
        "type": "object",
        "properties": {
            "scene_slug": {"type": "string", "description": "场景 slug"},
            "turn_text": {
                "type": "string",
                "description": "这一轮的记录：玩家做了什么、裁定结果、NPC 反应、环境变化",
            },
        },
        "required": ["scene_slug", "turn_text"],
    },
)
async def append_scene_dialogue(ctx: ToolContext, scene_slug: str, turn_text: str) -> str:
    if ctx.store.read("scenes", scene_slug) is None:
        return f"错误：场景 '{scene_slug}' 不存在。"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    chunk = f"### [{stamp}]\n{turn_text}"
    ctx.store.append_body("scenes", scene_slug, chunk)
    return f"已追加一轮记录到场景 {scene_slug}。"


@tool(
    "move_character_scene",
    "把角色从当前场景转移到新场景（由你决定，如玩家前往另一地点或被剧情带走）。"
    "更新场景归属映射与两个场景的在场者。用于裁决跨场景移动。",
    {
        "type": "object",
        "properties": {
            "char_slug": {"type": "string", "description": "角色 slug"},
            "new_scene_slug": {"type": "string", "description": "目标场景 slug"},
        },
        "required": ["char_slug", "new_scene_slug"],
    },
)
async def move_character_scene(ctx: ToolContext, char_slug: str, new_scene_slug: str) -> str:
    if ctx.store.read("scenes", new_scene_slug) is None:
        return f"错误：目标场景 '{new_scene_slug}' 不存在。"
    old = ctx.store.char_scene(ctx.group_id, char_slug)
    ctx.store.set_char_scene(ctx.group_id, char_slug, new_scene_slug)
    if old:
        _remove_attendee(ctx.store, old, char_slug)
    _append_attendee(ctx.store, new_scene_slug, char_slug)
    return f"角色 {char_slug} 从 {old or '（无）'} 转移到 {new_scene_slug}。"


# --- 支撑创作工具 -----------------------------------------------------------

@tool(
    "create_npc",
    "创建支撑剧情的配角/路人 NPC 并落盘到 data/npcs/。须与预置弧光与已有设定一致。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "NPC slug（英文连字符）"},
            "name": {"type": "string", "description": "姓名"},
            "identity": {"type": "string", "description": "身份"},
            "description": {"type": "string", "description": "外貌、性格、说话风格、背景"},
        },
        "required": ["slug", "name", "identity", "description"],
    },
)
async def create_npc(
    ctx: ToolContext, slug: str, name: str, identity: str, description: str
) -> str:
    body = f"## {name}\n\n- **身份**：{identity}\n\n{description}\n"
    ctx.store.write(
        "npcs",
        slug,
        {"名称": name, "身份": identity, "性质": "支撑剧情", "slug": slug},
        body,
    )
    return f"NPC {name}（{slug}）已落盘：data/npcs/{slug}.md"


@tool(
    "create_item",
    "创建支撑剧情的关键/线索道具并落盘到 data/items/。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "道具 slug"},
            "name": {"type": "string", "description": "名称"},
            "description": {"type": "string", "description": "外观、来历、用途"},
        },
        "required": ["slug", "name", "description"],
    },
)
async def create_item(ctx: ToolContext, slug: str, name: str, description: str) -> str:
    ctx.store.write(
        "items",
        slug,
        {"名称": name, "性质": "支撑剧情", "slug": slug},
        f"## {name}\n\n{description}\n",
    )
    return f"道具 {name}（{slug}）已落盘：data/items/{slug}.md"


@tool(
    "create_scene",
    "创建支撑剧情的临时/新场景并落盘到 data/scenes/。用于过渡场景或玩家前往新地点。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "场景 slug"},
            "name": {"type": "string", "description": "场景名称"},
            "location": {"type": "string", "description": "所属地点 slug 或描述"},
            "description": {"type": "string", "description": "生动的场景描写"},
        },
        "required": ["slug", "name", "description"],
    },
)
async def create_scene(
    ctx: ToolContext, slug: str, name: str, description: str, location: str = ""
) -> str:
    body = f"## 场景描写\n\n{description}\n\n## 对话与行动记录\n（游戏开始后由主持人追加）\n"
    ctx.store.write(
        "scenes",
        slug,
        {"名称": name, "性质": "支撑剧情 / 可回收", "地点": location, "在场者": [], "slug": slug},
        body,
    )
    return f"场景 {name}（{slug}）已落盘：data/scenes/{slug}.md"


@tool(
    "create_location",
    "创建支撑剧情的地点并落盘到 data/locations/。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "地点 slug"},
            "name": {"type": "string", "description": "地点名称"},
            "description": {"type": "string", "description": "描写、氛围、常驻"},
        },
        "required": ["slug", "name", "description"],
    },
)
async def create_location(
    ctx: ToolContext, slug: str, name: str, description: str
) -> str:
    ctx.store.write(
        "locations",
        slug,
        {"名称": name, "slug": slug},
        f"## {name}\n\n{description}\n",
    )
    return f"地点 {name}（{slug}）已落盘：data/locations/{slug}.md"


# --- 弧光与状态工具 ---------------------------------------------------------

@tool(
    "record_state",
    "记录一条游戏状态变化（关系/物品/状态改变/信息揭露），遵循连接原则："
    "必须写明触发者、影响对象、关联弧光与阶段、后续钩子。落盘到 data/state-records/。",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "状态变化标题"},
            "change_type": {
                "type": "string",
                "description": "变化类型：关系变化/物品获得/状态改变/信息揭露/其他",
            },
            "trigger": {"type": "string", "description": "触发者（PC/NPC/事件）"},
            "affected_chars": {"type": "string", "description": "受影响角色 slug，逗号分隔"},
            "affected_arcs": {
                "type": "string",
                "description": "关联弧光 slug；无则填「游离事件」",
            },
            "arc_stage": {
                "type": "string",
                "description": "关联到弧光的哪个阶段，如 矛盾积累；游离则留空",
            },
            "hooks": {"type": "string", "description": "后续可能催生的剧情走向，1-2 条"},
            "detail": {"type": "string", "description": "变化的来龙去脉"},
        },
        "required": ["title", "change_type", "trigger", "detail"],
    },
)
async def record_state(
    ctx: ToolContext,
    title: str,
    change_type: str,
    trigger: str,
    detail: str,
    affected_chars: str = "",
    affected_arcs: str = "",
    arc_stage: str = "",
    hooks: str = "",
) -> str:
    slug = store.slugify(title)
    date = datetime.now().strftime("%Y-%m-%d")
    name = f"{date}-{slug}"
    body = (
        f"## 概要\n\n- 变化类型：{change_type}\n- 一句话：{title}\n\n"
        f"## 连接信息\n\n- 触发者：{trigger}\n- 影响角色：{affected_chars or '无'}\n"
        f"- 弧光：{affected_arcs or '游离事件'}\n- 阶段：{arc_stage or '—'}\n"
        f"- 后续钩子：{hooks or '—'}\n\n## 详细\n\n{detail}\n"
    )
    ctx.store.write(
        "state-records",
        name,
        {"日期": date, "标题": title, "类型": change_type, "slug": name},
        body,
    )
    return f"状态记录已落盘：data/state-records/{name}.md"


@tool(
    "track_arc",
    "追踪主要（或自建）弧光的阶段推进：在弧光「状态变化记录」段追加引用，"
    "可选更新「当前阶段」指针。不改写四阶段设计蓝图。"
    "当玩家行动触发弧光阶段推进时调用。",
    {
        "type": "object",
        "properties": {
            "arc_slug": {"type": "string", "description": "弧光 slug"},
            "state_slug": {
                "type": "string",
                "description": "相关的状态记录 slug（record_state 的返回）",
            },
            "note": {"type": "string", "description": "本次推进说明"},
            "new_stage": {
                "type": "string",
                "description": "若阶段推进，填新阶段（启程/矛盾积累/高潮/新的稳定）；不变则留空",
            },
        },
        "required": ["arc_slug", "note"],
    },
)
async def track_arc(
    ctx: ToolContext,
    arc_slug: str,
    note: str,
    state_slug: str = "",
    new_stage: str = "",
) -> str:
    arc.track_arc(ctx.store, arc_slug, state_slug or "—", note, new_stage or None)
    return f"弧光 {arc_slug} 追踪已更新" + (f"，当前阶段→{new_stage}" if new_stage else "") + "。"


@tool(
    "plan_arc",
    "规划一条次要局部或单局弧光（你作为主持人有权规划这两级，主要弧光由备团用户预置你无权规划）。"
    "落盘标注级别/规划者/来源/平衡检查。触及高层次红线或过载时会报错。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "弧光 slug"},
            "level": {
                "type": "string",
                "enum": ["次要局部", "单局"],
                "description": "弧光级别（不可填「主要」）",
            },
            "title": {"type": "string", "description": "弧光名称"},
            "hook": {"type": "string", "description": "一句话梗概"},
            "body": {
                "type": "string",
                "description": "四阶段设计（启程/矛盾积累/高潮/新的稳定）的粗略走向",
            },
        },
        "required": ["slug", "level", "title", "hook", "body"],
    },
)
async def plan_arc(
    ctx: ToolContext, slug: str, level: str, title: str, hook: str, body: str
) -> str:
    arc.plan_arc(ctx.store, slug, level, title, hook, body)
    return f"{level}弧光 {title}（{slug}）已规划落盘。"


@tool(
    "query_memory",
    "只读检索游戏档案，返回摘要供你引用。可查角色/NPC/地点/场景/道具/弧光/状态记录。"
    "用于回答「之前发生了什么」「某 NPC 是谁」等回顾类问题，或决策前核实设定。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": [
                    "characters", "npcs", "locations", "scenes",
                    "items", "story-arcs", "state-records",
                ],
                "description": "要检索的档案类别",
            },
            "slug": {
                "type": "string",
                "description": "可选：指定 slug 读取完整内容；留空则列出该类全部摘要",
            },
        },
        "required": ["kind"],
    },
)
async def query_memory(ctx: ToolContext, kind: str, slug: str = "") -> str:
    if slug:
        d = ctx.store.read(kind, slug)
        if d is None:
            return f"未找到 {kind}/{slug}。"
        meta, body = d
        return f"## {kind}/{slug}\n\n元信息：{json.dumps(meta, ensure_ascii=False)}\n\n{body}"
    docs = ctx.store.list_docs(kind)
    if not docs:
        return f"{kind} 下暂无档案。"
    lines = [f"{kind} 共 {len(docs)} 条："]
    for d in docs:
        name = d["meta"].get("名称") or d["meta"].get("姓名") or d["meta"].get("标题") or d["slug"]
        extra = d["meta"].get("级别") or d["meta"].get("身份") or ""
        lines.append(f"- {d['slug']}：{name}" + (f"（{extra}）" if extra else ""))
    return "\n".join(lines)


# ===========================================================================
# 辅助渲染
# ===========================================================================

def _render_draft_card(draft: dict[str, Any]) -> str:
    lines = [
        "📝 角色卡草案（请回复「确认」或提出修改）：",
        "",
        f"姓名：{draft['name']}",
        f"身份：{draft['identity']}",
    ]
    if draft.get("appearance"):
        lines.append(f"外貌：{draft['appearance']}")
    if draft.get("personality"):
        lines.append(f"性格：{draft['personality']}")
    lines.append(f"背景：{draft['background']}")
    if draft.get("skills"):
        lines.append(f"能力：{draft['skills']}")
    if draft.get("hooks"):
        lines.append(f"剧情连接：{draft['hooks']}")
    return "\n".join(lines)


def _render_character_body(draft: dict[str, Any]) -> str:
    parts = [
        f"# {draft['name']}",
        "",
        "## 基础信息",
        f"- 姓名：{draft['name']}",
        f"- 身份：{draft['identity']}",
    ]
    if draft.get("appearance"):
        parts.append(f"- 外貌：{draft['appearance']}")
    parts.append("")
    parts.append("## 性格与背景")
    if draft.get("personality"):
        parts.append(f"- 性格：{draft['personality']}")
    parts.append(f"- 背景：{draft['background']}")
    if draft.get("skills"):
        parts.append("")
        parts.append("## 能力与资源")
        parts.append(draft["skills"])
    if draft.get("hooks"):
        parts.append("")
        parts.append("## 剧情连接")
        parts.append(draft["hooks"])
    return "\n".join(parts) + "\n"


def _append_attendee(s: store.Store, scene_slug: str, char_slug: str) -> None:
    """把角色加入场景的「在场者」列表（meta 字段，去重）。"""
    d = s.read("scenes", scene_slug)
    if d is None:
        return
    meta, body = d
    attendees = meta.get("在场者", []) or []
    if char_slug not in attendees:
        attendees.append(char_slug)
    meta["在场者"] = attendees
    s.write("scenes", scene_slug, meta, body)


def _remove_attendee(s: store.Store, scene_slug: str, char_slug: str) -> None:
    d = s.read("scenes", scene_slug)
    if d is None:
        return
    meta, body = d
    attendees = [a for a in (meta.get("在场者", []) or []) if a != char_slug]
    meta["在场者"] = attendees
    s.write("scenes", scene_slug, meta, body)


# ===========================================================================
# 上下文加载
# ===========================================================================

def _load_runtime_prompt() -> str:
    p = Path(__file__).resolve().parent / "gm_runtime.md"
    return p.read_text(encoding="utf-8")


def _load_context_text(s: store.Store, group_id: str, member_openid: str) -> str:
    """构造喂给 LLM 的当前局势文本。"""
    parts: list[str] = []
    char_slug = s.player_binding(member_openid)

    # 玩家绑定状态
    if char_slug:
        parts.append(f"## 当前玩家\n该玩家已绑定角色：{char_slug}")
        scene_slug = s.char_scene(group_id, char_slug)
        if scene_slug:
            parts.append(f"角色当前场景：{scene_slug}")
            d = s.read("scenes", scene_slug)
            if d:
                meta, body = d
                parts.append(f"### 场景 {meta.get('名称', scene_slug)}（{scene_slug}）")
                parts.append(body[:1500])
                attendees = meta.get("在场者", []) or []
                if attendees:
                    parts.append("在场者：" + "、".join(attendees))
    else:
        parts.append(
            "## 当前玩家\n该玩家尚未绑定角色。若其消息是概括叙述（如「我是个流浪剑客」），走角色创建流程。"
        )

    # 进行中弧光
    arcs_list = s.list_docs("story-arcs")
    active = [a for a in arcs_list if a["meta"].get("状态") == "进行中"]
    if active:
        parts.append("\n## 进行中的故事弧光")
        balance = arc.balance_report(s)
        parts.append(
            f"并行计数：主要 {balance.get('主要', 0)} / 单局 {balance.get('单局', 0)} "
            f"/ 次要局部 {balance.get('次要局部', 0)}"
        )
        for a in active:
            m = a["meta"]
            parts.append(
                f"- {a['slug']}：{m.get('名称', '')} | 级别:{m.get('级别', '')} "
                f"| 阶段:{m.get('当前阶段', '')} | 规划者:{m.get('规划者', '')}"
            )

    return "\n".join(parts)


def get_store() -> store.Store:
    """从 NoneBot 配置读取游戏目录，构造 Store（启动时已校验）。"""
    game_dir = get_driver().config.atrpg_game_dir
    return store.Store(game_dir)


# ===========================================================================
# matcher 入口
# ===========================================================================

group_at = on_message(rule=is_type(GroupAtMessageCreateEvent), priority=10, block=True)


@group_at.handle()
async def handle_group_at(bot: Bot, matcher: Matcher, event: GroupAtMessageCreateEvent) -> None:
    text = event.get_plaintext().strip()
    member_openid = event.author.member_openid
    group_id = event.group_openid

    if not text:
        return  # 空 @ 不处理

    try:
        s = get_store()
    except store.StoreError as e:
        await matcher.send(f"⚠ 游戏目录未就绪：{e}")
        return

    target_group = str(getattr(get_driver().config, "atrpg_target_group", "")).strip()
    if target_group and group_id != target_group:
        return  # 非目标群，忽略

    logger.info(f"GM 处理: group={group_id} member={member_openid} text={text[:40]!r}")

    ctx = ToolContext(store=s, member_openid=member_openid, group_id=group_id, raw_text=text)

    # 构造初始消息
    system_prompt = _load_runtime_prompt()
    context_text = _load_context_text(s, group_id, member_openid)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"# 当前局势\n{context_text}\n\n"
                f"# 玩家本轮发言\n玩家({member_openid})：{text}\n\n"
                f"请作为主持人处理。如需向玩家输出，用 reply 工具；"
                f"如需落盘，用对应工具。处理完毕后以 reply 收尾。"
            ),
        },
    ]

    # 工具调用循环
    schemas = tool_schemas()
    replied = False
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            assistant = await llm.chat_with_tools(messages, schemas)
        except Exception as e:  # noqa: BLE001 — LLM 调用失败要给玩家兜底
            logger.opt(exception=e).error("LLM 调用失败")
            if not ctx.replies:
                await matcher.send("⚠ 主持人暂时无法响应，请稍后再试。")
            break

        # 把助手这步加入消息历史
        messages.append(llm.assistant_to_message(assistant))

        if not assistant.has_tool_calls:
            # 模型收尾（未调工具）。若有文本残留也作为回复发出。
            if assistant.content.strip():
                ctx.replies.append(assistant.content)
            break

        # 执行工具调用
        for call in assistant.tool_calls:
            if call.name == "reply":
                replied = True
            result = await dispatch(ctx, call)
            messages.append(llm.tool_result_message(call.id, result))
        # 循环上限兜底：给模型继续的机会
    else:
        # 触达 MAX_TOOL_ROUNDS 仍未收尾
        if not ctx.replies:
            ctx.replies.append("（主持人处理超时，本轮已中断。请重试。）")
        logger.warning("工具调用循环达到上限，强制收尾")

    # 分块发送收集到的回复
    if not ctx.replies and not replied:
        ctx.replies.append("（主持人已处理，但没有产生回复内容。）")

    for chunk in _split_chunks(ctx.replies):
        await matcher.send(chunk)


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
