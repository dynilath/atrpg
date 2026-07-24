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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from nonebot import get_driver, logger, on_message
from nonebot.adapters.qq import Bot, C2CMessageCreateEvent, GroupAtMessageCreateEvent
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

    每个 @bot 消息新建一个。工具实现通过它访问 store / 群信息 / 发送回调。
    角色卡草案不再存内存——直接落盘到 data/characters/（状态:待确认），跨消息持久化。
    """

    store: store.Store
    member_openid: str
    group_id: str
    # 玩家本轮发送的原始文本
    raw_text: str
    # 发送回调：reply 工具调用时立即发群（流式回复），不等循环结束。
    # 由 handler 注入（包装 matcher.send）。
    send_fn: Callable[[str], Awaitable[None]] | None = None
    # 标记本轮是否已通过 reply 发过内容（用于判断兜底）
    replied: bool = False


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
    # 流式回复：reply 被调用时立即发群，不等工具循环结束。
    # 这样玩家快速看到演绎文本，落盘等后续工具调用在后台继续。
    if ctx.send_fn:
        for chunk in _split_chunks([content]):
            await ctx.send_fn(chunk)
    ctx.replied = True
    return "已发送给玩家。"


# --- 角色与场景工具 ---------------------------------------------------------

@tool(
    "draft_character",
    "当玩家给出概括叙述（如「我是个流浪剑客，在找失散的妹妹」）且尚未绑定角色时，"
    "生成完整角色卡草案并落盘到 data/characters/<slug>.md（状态标「待确认」）。"
    "草案含全量信息（含剧情钩子，落盘但仅主持人可见）；发给玩家的展示卡只含玩家可见字段。"
    "请基于玩家叙述补全外貌/性格/能力/背景，动机尽量挂接到已有主要弧光。",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "角色姓名"},
            "identity": {"type": "string", "description": "身份，如 流浪剑客 / 港口守卫"},
            "appearance": {"type": "string", "description": "外貌描写（2-4 句）"},
            "personality": {"type": "string", "description": "性格关键词与简述"},
            "background": {"type": "string", "description": "出身、经历、为何在此"},
            "skills": {"type": "string", "description": "核心技能与熟练度、属性倾向"},
            "hooks": {"type": "string", "description": "剧情连接：卷入哪条弧光、当前目标（主持人内部，不展示给玩家）"},
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
    slug = draft["slug"]

    # 草案即落盘到 characters/（状态「待确认」，含全量信息含 hooks）
    char_body = _render_character_body(draft)
    ctx.store.write(
        "characters",
        slug,
        {
            "姓名": name,
            "类型": "玩家角色",
            "身份": identity,
            "状态": "待确认",
            "slug": slug,
            "owner_openid": ctx.member_openid,
        },
        char_body,
    )

    # 发给玩家的是可见摘要卡（不含 hooks）——立即发送
    card = _render_player_card(draft)
    if ctx.send_fn:
        await ctx.send_fn(card)
    return (
        f"角色卡草案已落盘到 data/characters/{slug}.md（状态:待确认），角色卡已直接发送给玩家。"
        "**不要再调用 reply**——角色卡已发出。等待玩家下一条消息回复确认后，调用 finalize_character 转为正式。"
    )


@tool(
    "finalize_character",
    "玩家确认角色卡草案后，把待确认角色转为正式：改状态、绑定 QQ↔角色、"
    "把角色放入指定场景的在场者并记录场景归属。必须先用 draft_character 生成草案。",
    {
        "type": "object",
        "properties": {
            "char_slug": {
                "type": "string",
                "description": "待确认角色的 slug（draft_character 落盘时用的 slug）",
            },
            "scene_slug": {
                "type": "string",
                "description": "初始场景 slug（由你决定，不由玩家选）",
            },
        },
        "required": ["char_slug", "scene_slug"],
    },
)
async def finalize_character(ctx: ToolContext, char_slug: str, scene_slug: str) -> str:
    d = ctx.store.read("characters", char_slug)
    if d is None:
        return f"错误：角色 '{char_slug}' 不存在。请先用 draft_character 生成草案。"
    meta, body = d
    if meta.get("状态") != "待确认":
        return f"错误：角色 '{char_slug}' 状态为「{meta.get('状态')}」，不是待确认草案。"

    # 校验场景存在
    scene = ctx.store.read("scenes", scene_slug)
    if scene is None:
        return f"错误：场景 '{scene_slug}' 不存在。请用 query_memory 查可用场景或 create_scene 新建。"

    # 转为正式：改状态
    meta["状态"] = "正式"
    ctx.store.write("characters", char_slug, meta, body)

    # 绑定 QQ↔角色
    ctx.store.bind_player(ctx.member_openid, char_slug, meta.get("姓名", char_slug))
    # 场景归属 + 在场者追加
    ctx.store.set_char_scene(ctx.group_id, char_slug, scene_slug)
    scene_meta, _ = scene
    _append_attendee(ctx.store, scene_slug, char_slug)
    if ctx.send_fn:
        await ctx.send_fn(
            f"✓ 角色已转正式并绑定：data/characters/{char_slug}.md\n"
            f"✓ 初始场景：{scene_meta.get('名称', scene_slug)}"
        )
    return f"角色 {meta.get('姓名', char_slug)}（{char_slug}）已正式落盘并绑定，初始场景 {scene_slug}。"


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
        return f"## {kind}/{slug}\n\n元信息：{json.dumps(meta, ensure_ascii=False, default=str)}\n\n{body}"
    docs = ctx.store.list_docs(kind)
    if not docs:
        return f"{kind} 下暂无档案。"
    lines = [f"{kind} 共 {len(docs)} 条："]
    for d in docs:
        name = d["meta"].get("名称") or d["meta"].get("姓名") or d["meta"].get("标题") or d["slug"]
        extra = d["meta"].get("级别") or d["meta"].get("身份") or ""
        lines.append(f"- {d['slug']}：{name}" + (f"（{extra}）" if extra else ""))
    return "\n".join(lines)


@tool(
    "query_locations",
    "追踪角色位置与场景在场者。回答「某角色在哪」「某场景有谁」「所有角色位置」等问题。"
    "裁决跨场景移动、判断角色能否互动时也应先查询。",
    {
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["where_is", "who_in", "all"],
                "description": "where_is=查某角色在哪；who_in=查某场景有哪些角色；all=列出所有角色位置",
            },
            "char_slug": {"type": "string", "description": "where_is 时必填：要查的角色 slug"},
            "scene_slug": {"type": "string", "description": "who_in 时必填：要查的场景 slug"},
        },
        "required": ["query_type"],
    },
)
async def query_locations(
    ctx: ToolContext,
    query_type: str,
    char_slug: str = "",
    scene_slug: str = "",
) -> str:
    if query_type == "where_is":
        if not char_slug:
            return "错误：where_is 需提供 char_slug。"
        loc = ctx.store.char_scene(ctx.group_id, char_slug)
        if not loc:
            return f"角色 {char_slug} 当前无场景归属记录。"
        d = ctx.store.read("scenes", loc)
        if d is None:
            return f"角色 {char_slug} 在场景 {loc}，但场景档案不存在。"
        meta, body = d
        attendees = ctx.store.chars_in_scene(loc)
        others = [a for a in attendees if a != char_slug]
        return (
            f"角色 {char_slug} 当前在场景「{meta.get('名称', loc)}」（{loc}）。\n"
            f"场景描写：{body[:300]}\n"
            f"同场角色：{('、'.join(others)) if others else '无'}"
        )
    if query_type == "who_in":
        if not scene_slug:
            return "错误：who_in 需提供 scene_slug。"
        attendees = ctx.store.chars_in_scene(scene_slug)
        d = ctx.store.read("scenes", scene_slug)
        name = d[0].get("名称", scene_slug) if d else scene_slug
        if not attendees:
            return f"场景「{name}」（{scene_slug}）当前无角色在场。"
        return f"场景「{name}」（{scene_slug}）在场角色：{ '、'.join(attendees) }"
    if query_type == "all":
        locs = ctx.store.all_char_locations(ctx.group_id)
        if not locs:
            return "当前无角色位置记录。"
        lines = ["所有角色位置："]
        for c, s in locs.items():
            d = ctx.store.read("characters", c)
            cname = d[0].get("姓名", c) if d else c
            sd = ctx.store.read("scenes", s)
            sname = sd[0].get("名称", s) if sd else s
            lines.append(f"- {cname}（{c}）→ {sname}（{s}）")
        return "\n".join(lines)
    return f"错误：未知 query_type '{query_type}'。"


# ===========================================================================
# 辅助渲染
# ===========================================================================

def _render_player_card(draft: dict[str, Any]) -> str:
    """渲染玩家可见的角色卡摘要（不含 hooks/秘密等主持人内部信息）。"""
    lines = [
        "📝 角色卡（请回复「确认」接受，或提出修改）：",
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


def _load_system_prefix(s: store.Store) -> str:
    """构造稳定 system 前缀：运行时提示词 + 世界书 + 文风参考。

    这几部分每轮不变，作为消息列表首条，让 DeepSeek 等提供商的前缀缓存命中。
    """
    runtime = _load_runtime_prompt()
    parts = [runtime]
    world = s.read_world_book()
    if world:
        parts.append(f"---\n\n# 世界书（常驻世界观知识，你的设定依据）\n\n{world}")
    style = s.read_style_guide()
    if style:
        parts.append(f"---\n\n# 文风参考（叙事调性，演绎 NPC 台词与场景描写时模仿此风格）\n\n{style}")
    return "\n\n".join(parts)


def _build_sender_frame(s: store.Store, group_id: str, member_openid: str) -> str:
    """构造发送人框架：最小必要信息（谁在说话、关联角色、绑定状态）。

    精简设计——不塞场景描写/弧光详情，那些由 LLM 用 query_locations/query_memory 按需查。
    这样 user 消息短且稳定，历史续接干净，前缀缓存效率高。
    """
    char_slug = s.player_binding(member_openid)

    if char_slug:
        # 已绑定：带角色名 + 当前场景名（一行，不展开描写）
        d = s.read("characters", char_slug)
        char_name = d[0].get("姓名", char_slug) if d else char_slug
        char_identity = d[0].get("身份", "") if d else ""
        scene_slug = s.char_scene(group_id, char_slug)
        scene_name = ""
        if scene_slug:
            sd = s.read("scenes", scene_slug)
            scene_name = sd[0].get("名称", scene_slug) if sd else scene_slug
        loc = f" | 当前场景: {scene_name}" if scene_name else ""
        ident = f"（{char_identity}）" if char_identity else ""
        return f'<turn sender="{char_name}" char="{char_slug}"{loc}>\n状态: 已绑定角色{ident}'
    else:
        # 未绑定：检查是否有待确认草案
        pending = _find_pending_char(s, member_openid)
        if pending:
            pd = s.read("characters", pending)
            pname = pd[0].get("姓名", pending) if pd else pending
            return (
                f'<turn sender="未绑定玩家" pending_char="{pending}">\n'
                f'状态: 有待确认角色卡「{pname}」，若玩家确认则 finalize_character'
            )
        return '<turn sender="未绑定玩家">\n状态: 尚未绑定角色，若为概括叙述则走角色创建'


def _find_pending_char(s: store.Store, member_openid: str) -> str | None:
    """查找某玩家的待确认角色草案 slug（扫 characters/ 状态为待确认且 owner 匹配）。"""
    for d in s.list_docs("characters"):
        if d["meta"].get("状态") == "待确认" and d["meta"].get("owner_openid") == member_openid:
            return d["slug"]
    return None


def get_store() -> store.Store:
    """从 NoneBot 配置读取游戏目录，构造 Store（启动时已校验）。"""
    game_dir = get_driver().config.atrpg_game_dir
    return store.Store(game_dir)


# ===========================================================================
# matcher 入口
# ===========================================================================

# 同时监听群 @ 消息与 C2C 私聊消息。私聊是否真正处理由 c2c_test_mode 开关控制
# （见 handler 内），开关关闭时私聊事件进入 handler 后被忽略，开销极小。
group_at = on_message(
    rule=is_type(GroupAtMessageCreateEvent, C2CMessageCreateEvent),
    priority=10,
    block=True,
)


def _resolve_session(event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> tuple[str, str, bool]:
    """从事件提取 (member_openid, session_key, is_c2c)。

    群@消息：session_key = group_openid（按群隔离团会话）。
    C2C 私聊：session_key = c2c_<user_openid>（虚拟群号，每个私聊用户独立会话）。
    """
    if isinstance(event, C2CMessageCreateEvent):
        return event.author.user_openid, f"c2c_{event.author.user_openid}", True
    return event.author.member_openid, event.group_openid, False


@group_at.handle()
async def handle_group_at(bot: Bot, matcher: Matcher, event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> None:
    member_openid, group_id, is_c2c = _resolve_session(event)
    text = event.get_plaintext().strip()

    if not text:
        return  # 空消息不处理

    # 私聊需 c2c_test_mode 开关开启才处理（用于验证；正式跑团应关）
    if is_c2c and not getattr(get_driver().config, "atrpg_c2c_test_mode", False):
        return

    try:
        s = get_store()
    except store.StoreError as e:
        await matcher.send(f"⚠ 游戏目录未就绪：{e}")
        return

    # 仅群@消息做目标群过滤；私聊不过滤（测试模式下一对一验证）
    if not is_c2c:
        target_group = str(getattr(get_driver().config, "atrpg_target_group", "")).strip()
        if target_group and group_id != target_group:
            return  # 非目标群，忽略

    logger.info(f"GM 处理: {'c2c' if is_c2c else 'group'}={group_id} member={member_openid} text={text[:40]!r}")

    # 流式回复：reply 工具被调用时立即发群，不等循环结束。
    # 包装 matcher.send 为 send_fn 注入 ToolContext。
    # 捕获 QQ 去重错误（ActionFailed code=40054005）：不冒泡给 LLM，否则 LLM 会误以为
    # 没发成功而重试 reply，形成无效循环。去重说明 QQ 已收到或拦截，视为已发送。
    async def _send(content: str) -> None:
        import asyncio
        chunks = _split_chunks([content])
        for i, chunk in enumerate(chunks):
            if i > 0:
                await asyncio.sleep(0.5)  # 连续分块间小延迟，避免触发 QQ 去重
            try:
                await matcher.send(chunk)
            except Exception as e:
                # QQ 去重(40054005)等发送失败：记录但不冒泡，避免 LLM 重试循环
                logger.warning(f"发送消息到群失败（可能去重）：{e}")

    ctx = ToolContext(
        store=s, member_openid=member_openid, group_id=group_id,
        raw_text=text, send_fn=_send,
    )

    # ---- 对话历史续接 ----
    # 稳定前缀（gm_runtime + 世界书）作为首条 system；动态局势作为 user 消息每轮更新。
    # 历史从 .atrpg/history/<session>.json 加载，本轮工具循环的消息追加进历史，结束后保存。
    # 这样：1) 不每轮重传全部上下文（复用历史）；2) 稳定前缀不变，命中 DeepSeek 前缀缓存。
    session_key = group_id
    history = s.load_history(session_key)

    # 每轮刷新稳定前缀（世界书可能更新）
    system_prefix = _load_system_prefix(s)
    # 发送人框架：精简（角色名/场景名一行），详情由 LLM 用 query_locations/query_memory 按需查
    sender_frame = _build_sender_frame(s, group_id, member_openid)
    turn_user = f"{sender_frame}\n\n{text}\n</turn>"

    # 构造本轮 messages：新 system 前缀（首条）+ 历史（去掉旧 system）+ 本轮 user
    # 显式过滤历史里的 system 消息（用新前缀替代），不依赖位置
    history_body = [m for m in history if m.get("role") != "system"]
    if history_body:
        messages = [{"role": "system", "content": system_prefix}] + history_body + [{"role": "user", "content": turn_user}]
    else:
        # 首次对话：给 LLM 一句引导，告知可用工具查详情
        messages = [
            {"role": "system", "content": system_prefix},
            {"role": "user", "content": turn_user + "\n\n（首次对话。如需了解当前场景/在场者/已有弧光，用 query_locations / query_memory 工具查询。处理完毕用 reply 收尾。）"},
        ]

    # 工具调用循环（流式：reply 工具被调用时立即发群）
    schemas = tool_schemas()
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            assistant = await llm.chat_with_tools(messages, schemas)
        except Exception as e:  # noqa: BLE001 — LLM 调用失败要给玩家兜底
            logger.opt(exception=e).error("LLM 调用失败")
            if not ctx.replied:
                await matcher.send("⚠ 主持人暂时无法响应，请稍后再试。")
            break

        # 输出 token 用量与缓存命中
        u = assistant.usage
        if u:
            logger.info(
                f"LLM 用量: prompt={u.get('prompt_tokens', 0)} "
                f"cached={u.get('cached_tokens', 0)}/{u.get('prompt_tokens', 0)} "
                f"completion={u.get('completion_tokens', 0)}"
            )

        # 把助手这步加入消息历史
        messages.append(llm.assistant_to_message(assistant))

        if not assistant.has_tool_calls:
            # 模型收尾（未调工具）。若有文本残留且本轮还没 reply 过，作为回复发出。
            if assistant.content.strip() and not ctx.replied:
                await _send(assistant.content)
                ctx.replied = True
            break

        # 执行工具调用（reply 会立即发群，落盘工具在后台继续）
        for call in assistant.tool_calls:
            result = await dispatch(ctx, call)
            messages.append(llm.tool_result_message(call.id, result))
        # 循环上限兜底：给模型继续的机会
    else:
        # 触达 MAX_TOOL_ROUNDS 仍未收尾
        if not ctx.replied:
            await matcher.send("（主持人处理超时，本轮已中断。请重试。）")
        logger.warning("工具调用循环达到上限，强制收尾")

    # 保存对话历史（含本轮所有新增消息）
    s.save_history(session_key, messages)

    # 兜底：如果整个循环没产生任何回复
    if not ctx.replied:
        await matcher.send("（主持人已处理，但没有产生回复内容。）")


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
