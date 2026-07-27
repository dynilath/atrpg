"""tools.py --- 主持人工具注册表（纯逻辑，零平台依赖）。

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
    "【必须调用】向玩家发送消息，是唯一出口——不调 reply 玩家什么也看不到。"
    "内容可包含演绎文本、NPC 台词、裁决结果、场景描写。"
    "所有要给玩家看的文本必须放在 content 参数里，不要写在 assistant 消息正文然后传空参数。"
    "长篇幅叙事可分多次 reply；每次应自成一体。",
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
    return f"已发送（{len(content)}字）"


# --- 角色与情景工具 ---------------------------------------------------------

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
    draft = {
        "name": name, "identity": identity, "appearance": appearance,
        "personality": personality, "background": background,
        "skills": skills, "hooks": hooks, "slug": store.slugify(name),
    }
    slug = draft["slug"]
    hue = store.char_color(name)

    char_body = _render_character_body(draft)
    ctx.store.write(
        "characters", slug,
        {"name": name, "type": "玩家角色", "identity": identity, "status": "待确认",
         "slug": slug, "owner_openid": ctx.member_openid, "color": hue},
        char_body,
    )

    card = _render_player_card(draft)
    if ctx.send_fn:
        await ctx.send_fn(card)
    return (
        f"角色卡草案已落盘到 data/characters/{slug}.md（状态:待确认）。"
        f"角色卡可见摘要已直接发送给玩家（不含剧情钩子等内部信息）。"
        "等待玩家下一条消息回复确认后，调用 finalize_character 转为正式。"
    )


@tool(
    "finalize_character",
    "玩家确认角色卡草案后，把待确认角色转为正式：改状态、绑定 QQ↔角色、"
    "把角色放入指定情景的在场者并记录归属。必须先用 draft_character 生成草案。",
    {
        "type": "object",
        "properties": {
            "char_slug": {"type": "string", "description": "待确认角色的 slug（draft_character 落盘时用的 slug）"},
            "scene_slug": {"type": "string", "description": "初始情景 slug（由你决定，不由玩家选）"},
        },
        "required": ["char_slug", "scene_slug"],
    },
)
async def finalize_character(ctx: ToolContext, char_slug: str, scene_slug: str) -> str:
    d = ctx.store.read("characters", char_slug)
    if d is None:
        return f"错误：角色 '{char_slug}' 不存在。请先用 draft_character 生成草案。"
    meta, body = d
    if meta.get("status") != "待确认":
        return f"错误：角色 '{char_slug}' 状态为「{meta.get('status')}」，不是待确认草案。"

    scene = ctx.store.read("scenes", scene_slug)
    if scene is None:
        return f"错误：情景 '{scene_slug}' 不存在。请用 query_memory 查可用情景或 create_scene 新建。"

    meta["status"] = "正式"
    ctx.store.write("characters", char_slug, meta, body)
    ctx.store.bind_player(ctx.member_openid, char_slug, meta.get("name", char_slug))
    ctx.store.set_char_scene(ctx.group_id, char_slug, scene_slug)
    if ctx.send_fn:
        await ctx.send_fn(
            f"✓ 角色已转正式并绑定：data/characters/{char_slug}.md\n"
            f"✓ 初始情景：{scene_meta.get('name', scene_slug)}"
        )
    return f"角色 {meta.get('name', char_slug)}（{char_slug}）已正式落盘并绑定，初始情景 {scene_slug}。"


@tool(
    "append_scene_dialogue",
    "向某情境的「对话与行动记录」追加一轮（玩家行动 + 你的裁决 + NPC 反应 + 环境推进）。"
    "每次玩家行动裁决后都应调用，以保证剧情持久化。",
    {
        "type": "object",
        "properties": {
            "scene_slug": {"type": "string", "description": "情境 slug"},
            "turn_text": {"type": "string", "description": "这一轮的记录：玩家做了什么、裁定结果、NPC 反应、环境变化"},
        },
        "required": ["scene_slug", "turn_text"],
    },
)
async def append_scene_dialogue(ctx: ToolContext, scene_slug: str, turn_text: str) -> str:
    if ctx.store.read("scenes", scene_slug) is None:
        return f"错误：情景 '{scene_slug}' 不存在。"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    chunk = f"### [{stamp}]\n{turn_text}"
    ctx.store.append_body("scenes", scene_slug, chunk)
    return f"已追加一轮记录到情景 {scene_slug}。"


@tool(
    "move_character_scene",
    "把角色从当前情境转移到新情境（由你决定，如玩家前往另一地点或被剧情带走）。"
    "更新情境归属映射与两个情境的在场者。用于裁决跨情境移动。",
    {
        "type": "object",
        "properties": {
            "char_slug": {"type": "string", "description": "角色 slug"},
            "new_scene_slug": {"type": "string", "description": "目标情景 slug"},
        },
        "required": ["char_slug", "new_scene_slug"],
    },
)
async def move_character_scene(ctx: ToolContext, char_slug: str, new_scene_slug: str) -> str:
    if ctx.store.read("scenes", new_scene_slug) is None:
        return f"错误：目标情景 '{new_scene_slug}' 不存在。"
    old = ctx.store.char_scene(ctx.group_id, char_slug)
    ctx.store.set_char_scene(ctx.group_id, char_slug, new_scene_slug)
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
    ctx.store.write("npcs", slug, {"name": name, "identity": identity, "nature": "支撑剧情", "slug": slug}, body)
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
    ctx.store.write("items", slug, {"name": name, "nature": "支撑剧情", "slug": slug}, f"## {name}\n\n{description}\n")
    return f"道具 {name}（{slug}）已落盘：data/items/{slug}.md"


@tool(
    "create_scene",
    "在某个地点内创建一段情景（连续事件片段）并落盘到 data/scenes/。"
    "情景不是地点本身——必须先有对应地点（data/locations/）。"
    "每个情景通过 location 字段关联到所属地点。用于玩家进入新区域或触发新事件时。",
    {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "情景 slug"},
            "name": {"type": "string", "description": "情景名称"},
            "location": {"type": "string", "description": "所属地点 slug（必填，须先存在）"},
            "description": {"type": "string", "description": "生动的情景描写（含该地点当前发生的事情）"},
        },
        "required": ["slug", "name", "location", "description"],
    },
)
async def create_scene(ctx: ToolContext, slug: str, name: str, description: str, location: str = "") -> str:
    body = f"## 情境描写\n\n{description}\n\n## 对话与行动记录\n（游戏开始后由主持人追加）\n"
    ctx.store.write("scenes", slug, {"name": name, "nature": "支撑剧情 / 可回收", "location": location, "slug": slug}, body)
    return f"情境 {name}（{slug}）已落盘：data/scenes/{slug}.md"


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
    ctx.store.write("locations", slug, {"name": name, "slug": slug}, f"## {name}\n\n{description}\n")
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
        f"- 弧光：{affected_arcs or '游离事件'}\n- 阶段：{arc_stage or '---'}\n"
        f"- 后续钩子：{hooks or '---'}\n\n## 详细\n\n{detail}\n"
    )
    ctx.store.write("state-records", name, {"date": date, "title": title, "type": change_type, "slug": name}, body)
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
    arc.track_arc(ctx.store, arc_slug, state_slug or "---", note, new_stage or None)
    return f"弧光 {arc_slug} 追踪已更新" + (f"，当前阶段->{new_stage}" if new_stage else "") + "。"


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
    "只读检索游戏档案，返回摘要供你引用。可查角色/NPC/地点/情景/道具/弧光/状态记录/设定术语。"
    "用于回答「之前发生了什么」「某 NPC 是谁」等回顾类问题，或决策前核实设定。"
    "当 kind=\"terminology\" 时，建议提供 search 参数按关键词搜索术语（匹配术语名/别名/正文）。",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["characters", "npcs", "locations", "scenes", "items", "story-arcs", "state-records", "terminology"], "description": "要检索的档案类别"},
            "slug": {"type": "string", "description": "可选：指定 slug 读取完整内容；留空则列出该类全部摘要"},
            "search": {"type": "string", "description": "可选：关键词搜索（不区分大小写）。匹配 meta 字段与正文。尤其适合 terminology——用术语名/别名搜索，不用猜 slug"},
        },
        "required": ["kind"],
    },
)
async def query_memory(ctx: ToolContext, kind: str, slug: str = "", search: str = "") -> str:
    if slug:
        d = ctx.store.read(kind, slug)
        if d is None:
            return f"未找到 {kind}/{slug}。"
        meta, body = d
        return f"## {kind}/{slug}\n\n元信息：{json.dumps(meta, ensure_ascii=False, default=str)}\n\n{body}"
    docs = ctx.store.list_docs(kind)
    if not docs:
        return f"{kind} 下暂无档案。"

    # 关键词搜索
    if search:
        matched = []
        search_lower = search.lower()
        for d in docs:
            score = 0
            # 匹配 meta 字段
            meta_str = json.dumps(d["meta"], ensure_ascii=False, default=str).lower()
            score += meta_str.count(search_lower) * 3  # meta 命中权重更高
            # 匹配 slug
            if search_lower in d["slug"].lower():
                score += 5  # slug 精确命中最高权重
            # 读取 body 匹配
            try:
                _, body = ctx.store.read(kind, d["slug"]) or ({}, "")
                score += body.lower().count(search_lower)
            except Exception:
                pass
            if score > 0:
                d["_score"] = score
                matched.append(d)
        if not matched:
            return f"{kind} 下未找到匹配「{search}」的条目。"
        matched.sort(key=lambda x: x["_score"], reverse=True)
        lines = [f"{kind} 搜索「{search}」找到 {len(matched)} 条："]
        for d in matched[:10]:
            name = d["meta"].get("name") or d["meta"].get("title") or d["meta"].get("term") or d["slug"]
            extra = d["meta"].get("level") or d["meta"].get("identity") or d["meta"].get("category") or d["meta"].get("brief") or ""
            lines.append(f"- {d['slug']}：{name}" + (f"（{extra}）" if extra else ""))
        if len(matched) > 10:
            lines.append(f"...还有 {len(matched) - 10} 条，请缩小搜索词")
        return "\n".join(lines)

    lines = [f"{kind} 共 {len(docs)} 条："]
    for d in docs:
        name = d["meta"].get("名称") or d["meta"].get("姓名") or d["meta"].get("标题") or d["meta"].get("术语") or d["slug"]
        extra = d["meta"].get("级别") or d["meta"].get("身份") or d["meta"].get("类别") or ""
        lines.append(f"- {d['slug']}：{name}" + (f"（{extra}）" if extra else ""))
    return "\n".join(lines)


@tool(
    "query_locations",
    "查询角色/NPC所在的地点与情景。每个情景属于一个地点（如「简报室」情景属于「三角机构分部」地点）。"
    "where_is 返回：地点 → 情景 → 同场者。who_in 返回：地点 → 情景 → 在场者。all 列出全部。"
    "裁决跨情景移动、判断角色能否互动前先查询。",
    {
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "enum": ["where_is", "who_in", "all"], "description": "where_is=查某角色在哪（返回地点+情景）；who_in=查某情景有谁（返回地点+情景）；all=列出所有角色位置"},
            "char_slug": {"type": "string", "description": "where_is 时必填：要查的角色或 NPC slug"},
            "scene_slug": {"type": "string", "description": "who_in 时必填：要查的情景 slug"},
        },
        "required": ["query_type"],
    },
)
async def query_locations(ctx: ToolContext, query_type: str, char_slug: str = "", scene_slug: str = "") -> str:
    if query_type == "where_is":
        if not char_slug:
            return "错误：where_is 需提供 char_slug。"
        # 先试角色，再试 NPC
        loc = ctx.store.char_current_scene(char_slug) or ctx.store.npc_current_scene(char_slug)
        if not loc:
            loc = ctx.store.char_scene(ctx.group_id, char_slug)  # 回退 session map
        if not loc:
            return f"{char_slug} 当前无情景归属记录。"
        d = ctx.store.read("scenes", loc)
        if d is None:
            return f"{char_slug} 在情景 {loc}，但情景档案不存在。"
        meta, body = d
        chars, npcs = ctx.store.who_in_scene(loc)
        others = [a for a in chars if a != char_slug] + npcs
        other_names = []
        for a in others:
            ad = ctx.store.read("characters", a) or ctx.store.read("npcs", a)
            other_names.append(ad[0].get("name", a) if ad else a)
        lines = []
        # 地点信息优先
        location_slug = meta.get("location")
        if location_slug:
            loc_name = ctx.store.location_name(location_slug)
            if loc_name:
                lines.append(f"地点：{loc_name}（{location_slug}）")
            else:
                lines.append(f"地点：{location_slug}（档案缺失）")
        else:
            lines.append(f"地点：未设定")
        # 情景信息
        lines.append(f"情景：{meta.get('name', loc)}（{loc}）")
        lines.append(f"情景描写：{body[:300]}")
        lines.append(f"同场：{'、'.join(other_names) if other_names else '无'}")
        return "\n".join(lines)
    if query_type == "who_in":
        if not scene_slug:
            return "错误：who_in 需提供 scene_slug。"
        chars, npcs = ctx.store.who_in_scene(scene_slug)
        d = ctx.store.read("scenes", scene_slug)
        name = d[0].get("name", scene_slug) if d else scene_slug
        lines = []
        location_slug = d[0].get("location") if d else None
        if location_slug:
            loc_name = ctx.store.location_name(location_slug) or location_slug
            lines.append(f"地点：{loc_name}（{location_slug}）")
        lines.append(f"情景：{name}（{scene_slug}）")
        all_attendees = chars + npcs
        if not all_attendees:
            lines.append("当前无角色或 NPC 在场。")
        else:
            lines.append(f"在场：{'、'.join(all_attendees)}")
        return "\n".join(lines)
    if query_type == "all":
        locs = ctx.store.all_char_locations(ctx.group_id)
        if not locs:
            return "当前无角色位置记录。"
        lines = ["所有角色/NPC位置："]
        for c, s in locs.items():
            d = ctx.store.read("characters", c) or ctx.store.read("npcs", c)
            cname = d[0].get("name", c) if d else c
            sd = ctx.store.read("scenes", s)
            sname = sd[0].get("name", s) if sd else s
            lines.append(f"- {cname}（{c}）-> {sname}（{s}）")
        return "\n".join(lines)
    return f"错误：未知 query_type '{query_type}'。"


# --- 情景状态查询 -----------------------------------------------------------

@tool(
    "query_scene_state",
    "查询某个地点的最新情景状态。当玩家返回之前离开的地点、切换到焦点外的情景、"
    "或需要知道某个地点'上次发生了什么'时调用。"
    "按文件名日期时间排序，自动取最新情景。"
    "返回：情景名称、游戏内时间、在场角色及其状态、最近事件摘要。",
    {
        "type": "object",
        "properties": {
            "location_slug": {
                "type": "string",
                "description": "地点 slug，如 triad-branch-office",
            },
        },
        "required": ["location_slug"],
    },
)
async def query_scene_state(ctx: ToolContext, location_slug: str) -> str:
    docs = ctx.store.list_docs("scenes")
    # 按文件名筛选属于该地点的镜头（文件名含 location_slug）
    candidates = []
    for d in docs:
        if location_slug in d["slug"]:
            candidates.append(d)
    if not candidates:
        # 也搜一下 location front matter
        for d in docs:
            meta = ctx.store.read("scenes", d["slug"])
            if meta and meta[0].get("location") == location_slug:
                candidates.append(d)

    if not candidates:
        return f"地点 {location_slug} 尚未有任何情景记录。"

    # 文件名格式 {YYYY-MM-DD}_{HHMM}-... — 字符序即为时间序
    candidates.sort(key=lambda d: d["slug"], reverse=True)
    latest = candidates[0]
    meta, body = ctx.store.read("scenes", latest["slug"])

    scene_time = meta.get("time", "未知时间")
    scene_name = meta.get("name", latest["slug"])
    chars, npcs = ctx.store.who_in_scene(latest["slug"])
    attendees = chars + npcs

    # 提取在场角色状态段（如果存在）
    char_state = ""
    if "## 在场角色状态" in body:
        cs_start = body.index("## 在场角色状态")
        cs_end = body.find("\n## ", cs_start + 1)
        if cs_end == -1:
            cs_end = len(body)
        char_state = body[cs_start:cs_end].strip()

    # 提取最后几行事件推进
    event_summary = ""
    if "## 事件推进" in body:
        ev_start = body.rindex("## 事件推进")
        tail = body[ev_start:]
        lines = [l for l in tail.split("\n") if l.strip() and not l.strip().startswith("#") and not l.strip().startswith(">")]
        # 取最近 5 条非标题行
        recent = lines[-5:] if len(lines) > 5 else lines
        event_summary = "\n".join(recent)

    parts = [
        f"📍 {scene_name}（{scene_time}）",
        f"在场角色: {', '.join(attendees) if attendees else '无'}",
    ]
    if char_state:
        parts.append(f"\n{char_state}")
    if event_summary:
        parts.append(f"\n最近事件:\n{event_summary}")

    # 如果有更早的镜头，提示
    if len(candidates) > 1:
        prev = candidates[1]
        parts.append(f"\n（更早的镜头: {prev['slug']}，共 {len(candidates)} 个镜头）")

    return "\n".join(parts)


# --- 骰子工具 ---------------------------------------------------------------

@tool(
    "roll_dice",
    "掷骰子工具。接受 dicelet 骰子表达式（如 2d6+3、4d6k3、d20+5、3#6d6），返回掷骰结果。"
    "用于 TRPG 中的随机裁决：属性检定、技能判定、战斗伤害、随机事件、运气判定等。"
    "你应在裁决玩家行动需要随机性时调用此工具，不要自己编造掷骰结果。",
    {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "dicelet 骰子表达式。常用语法："
                    "d20 — 1个20面骰；"
                    "2d6+3 — 2个6面骰结果加3；"
                    "4d6k3 — 4个6面骰取最高的3个（如 D&D 属性生成）；"
                    "d100 — 1个100面骰（百分骰）；"
                    "3#d20 — 掷3次d20（多组结果集）；"
                    "2d20k1 — 优势（取最高）；"
                    "2d20kl1 — 劣势（取最低）"
                ),
            },
        },
        "required": ["expression"],
    },
)
async def roll_dice(ctx: ToolContext, expression: str) -> str:
    try:
        import dicelet  # type: ignore[import-untyped]
    except ImportError:
        return "错误：dicelet 未安装。请运行 pip install dicelet 安装骰子引擎。"

    try:
        result = dicelet.roll(expression)
        return result.full
    except Exception as e:
        return f"掷骰错误：{e}"


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
