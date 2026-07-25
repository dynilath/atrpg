"""tools.py — 主持人工具注册表（纯逻辑，零平台依赖）。

从 gm.py 中提取，供 process_turn 直接导入，不再依赖 NoneBot。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from . import arc, llm, store
from .process_turn import ToolContext, _split_chunks

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    schema: dict[str, Any]
    func: Callable[..., Awaitable[str]]


_REGISTRY: dict[str, ToolDef] = {}


def tool(name: str, description: str, params: dict[str, Any]):
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
    return [td.schema for td in _REGISTRY.values()]


async def dispatch(ctx: ToolContext, call: llm.ToolCall) -> str:
    td = _REGISTRY.get(call.name)
    if td is None:
        return f"错误：未知工具 '{call.name}'"
    try:
        return await td.func(ctx, **call.arguments)
    except (arc.ArcError, store.StoreError) as e:
        return f"错误：{e}"
    except Exception:
        logger.warning(f"工具 {call.name} 执行异常", exc_info=True)
        return f"错误：执行 {call.name} 时发生内部错误"


# ===========================================================================
# 工具实现
# ===========================================================================

# --- 回复工具 ---------------------------------------------------------------

@tool(
    "reply",
    "向玩家发送消息（演绎文本、NPC 台词、裁决结果、场景描写）。"
    "这是把内容发到 QQ 群的唯一出口。**所有要给玩家看的文本必须放在 content 参数里**——"
    "不要把演绎文本写在 assistant 消息正文（content 字段）然后调 reply 传空参数，"
    "那会导致内容丢失。一轮只调一次 reply，把全部内容放进去。",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要发给玩家的完整文本（演绎/NPC台词/裁决），必填，不能为空"},
        },
        "required": ["content"],
    },
)
async def reply(ctx: ToolContext, content: str) -> str:
    if not content or not content.strip():
        return "错误：reply 的 content 不能为空。把要发给玩家的文本放进 content 参数。"
    if ctx.send_fn:
        for chunk in _split_chunks([content]):
            await ctx.send_fn(chunk)
    ctx.replied = True
    ctx.reply_preview = content[:120]
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
    ctx: ToolContext, name: str, identity: str, background: str,
    appearance: str = "", personality: str = "", skills: str = "", hooks: str = "",
) -> str:
    if ctx.store.player_binding(ctx.member_openid):
        return "错误：该玩家已绑定角色，不能再次创建。请用行动处理。"

    draft = {
        "name": name, "identity": identity, "appearance": appearance,
        "personality": personality, "background": background,
        "skills": skills, "hooks": hooks, "slug": store.slugify(name),
    }
    slug = draft["slug"]

    char_body = _render_character_body(draft)
    ctx.store.write(
        "characters", slug,
        {"姓名": name, "类型": "玩家角色", "身份": identity, "状态": "待确认",
         "slug": slug, "owner_openid": ctx.member_openid},
        char_body,
    )

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
            "char_slug": {"type": "string", "description": "待确认角色的 slug（draft_character 落盘时用的 slug）"},
            "scene_slug": {"type": "string", "description": "初始场景 slug（由你决定，不由玩家选）"},
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

    scene = ctx.store.read("scenes", scene_slug)
    if scene is None:
        return f"错误：场景 '{scene_slug}' 不存在。请用 query_memory 查可用场景或 create_scene 新建。"

    meta["状态"] = "正式"
    ctx.store.write("characters", char_slug, meta, body)
    ctx.store.bind_player(ctx.member_openid, char_slug, meta.get("姓名", char_slug))
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
            "turn_text": {"type": "string", "description": "这一轮的记录：玩家做了什么、裁定结果、NPC 反应、环境变化"},
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
async def create_npc(ctx: ToolContext, slug: str, name: str, identity: str, description: str) -> str:
    body = f"## {name}\n\n- **身份**：{identity}\n\n{description}\n"
    ctx.store.write("npcs", slug, {"名称": name, "身份": identity, "性质": "支撑剧情", "slug": slug}, body)
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
    ctx.store.write("items", slug, {"名称": name, "性质": "支撑剧情", "slug": slug}, f"## {name}\n\n{description}\n")
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
async def create_scene(ctx: ToolContext, slug: str, name: str, description: str, location: str = "") -> str:
    body = f"## 场景描写\n\n{description}\n\n## 对话与行动记录\n（游戏开始后由主持人追加）\n"
    ctx.store.write("scenes", slug, {"名称": name, "性质": "支撑剧情 / 可回收", "地点": location, "在场者": [], "slug": slug}, body)
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
async def create_location(ctx: ToolContext, slug: str, name: str, description: str) -> str:
    ctx.store.write("locations", slug, {"名称": name, "slug": slug}, f"## {name}\n\n{description}\n")
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
            "change_type": {"type": "string", "description": "变化类型：关系变化/物品获得/状态改变/信息揭露/其他"},
            "trigger": {"type": "string", "description": "触发者（PC/NPC/事件）"},
            "affected_chars": {"type": "string", "description": "受影响角色 slug，逗号分隔"},
            "affected_arcs": {"type": "string", "description": "关联弧光 slug；无则填「游离事件」"},
            "arc_stage": {"type": "string", "description": "关联到弧光的哪个阶段，如 矛盾积累；游离则留空"},
            "hooks": {"type": "string", "description": "后续可能催生的剧情走向，1-2 条"},
            "detail": {"type": "string", "description": "变化的来龙去脉"},
        },
        "required": ["title", "change_type", "trigger", "detail"],
    },
)
async def record_state(
    ctx: ToolContext, title: str, change_type: str, trigger: str, detail: str,
    affected_chars: str = "", affected_arcs: str = "", arc_stage: str = "", hooks: str = "",
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
    ctx.store.write("state-records", name, {"日期": date, "标题": title, "类型": change_type, "slug": name}, body)
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
            "state_slug": {"type": "string", "description": "相关的状态记录 slug（record_state 的返回）"},
            "note": {"type": "string", "description": "本次推进说明"},
            "new_stage": {"type": "string", "description": "若阶段推进，填新阶段（启程/矛盾积累/高潮/新的稳定）；不变则留空"},
        },
        "required": ["arc_slug", "note"],
    },
)
async def track_arc(ctx: ToolContext, arc_slug: str, note: str, state_slug: str = "", new_stage: str = "") -> str:
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
            "level": {"type": "string", "enum": ["次要局部", "单局"], "description": "弧光级别（不可填「主要」）"},
            "title": {"type": "string", "description": "弧光名称"},
            "hook": {"type": "string", "description": "一句话梗概"},
            "body": {"type": "string", "description": "四阶段设计（启程/矛盾积累/高潮/新的稳定）的粗略走向"},
        },
        "required": ["slug", "level", "title", "hook", "body"],
    },
)
async def plan_arc(ctx: ToolContext, slug: str, level: str, title: str, hook: str, body: str) -> str:
    arc.plan_arc(ctx.store, slug, level, title, hook, body)
    return f"{level}弧光 {title}（{slug}）已规划落盘。"


@tool(
    "query_memory",
    "只读检索游戏档案，返回摘要供你引用。可查角色/NPC/地点/场景/道具/弧光/状态记录。"
    "用于回答「之前发生了什么」「某 NPC 是谁」等回顾类问题，或决策前核实设定。",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["characters", "npcs", "locations", "scenes", "items", "story-arcs", "state-records"], "description": "要检索的档案类别"},
            "slug": {"type": "string", "description": "可选：指定 slug 读取完整内容；留空则列出该类全部摘要"},
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
            "query_type": {"type": "string", "enum": ["where_is", "who_in", "all"], "description": "where_is=查某角色在哪；who_in=查某场景有哪些角色；all=列出所有角色位置"},
            "char_slug": {"type": "string", "description": "where_is 时必填：要查的角色 slug"},
            "scene_slug": {"type": "string", "description": "who_in 时必填：要查的场景 slug"},
        },
        "required": ["query_type"],
    },
)
async def query_locations(ctx: ToolContext, query_type: str, char_slug: str = "", scene_slug: str = "") -> str:
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
        return f"场景「{name}」（{scene_slug}）在场角色：{'、'.join(attendees)}"
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
    lines = ["📝 角色卡（请回复「确认」接受，或提出修改）：", "", f"姓名：{draft['name']}", f"身份：{draft['identity']}"]
    if draft.get("appearance"):
        lines.append(f"外貌：{draft['appearance']}")
    if draft.get("personality"):
        lines.append(f"性格：{draft['personality']}")
    lines.append(f"背景：{draft['background']}")
    if draft.get("skills"):
        lines.append(f"能力：{draft['skills']}")
    return "\n".join(lines)


def _render_character_body(draft: dict[str, Any]) -> str:
    parts = ["# " + draft["name"], "", "## 基础信息", f"- 姓名：{draft['name']}", f"- 身份：{draft['identity']}"]
    if draft.get("appearance"):
        parts.append(f"- 外貌：{draft['appearance']}")
    parts.append(""); parts.append("## 性格与背景")
    if draft.get("personality"):
        parts.append(f"- 性格：{draft['personality']}")
    parts.append(f"- 背景：{draft['background']}")
    if draft.get("skills"):
        parts.append(""); parts.append("## 能力与资源"); parts.append(draft["skills"])
    if draft.get("hooks"):
        parts.append(""); parts.append("## 剧情连接"); parts.append(draft["hooks"])
    return "\n".join(parts) + "\n"


def _append_attendee(s: store.Store, scene_slug: str, char_slug: str) -> None:
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
