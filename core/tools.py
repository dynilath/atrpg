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
from .process_turn import ToolContext

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

# --- 待发送文档（outbox）工具 -------------------------------------------------

@tool(
    "outbox_append",
    "【必须调用】把要发给玩家的内容**追加**到待发送文档（outbox）末尾。"
    "这是玩家看到内容的唯一出口——turn 结束时文档内容会统一自动发送，不调它玩家什么也看不到。"
    "内容可包含演绎文本、NPC 台词、裁决结果、情景描写。"
    "所有要给玩家看的文本必须放在 content 参数里，不要写在 assistant 消息正文然后传空参数。"
    "长篇幅叙事可分多次 outbox_append；每次应自成一体。"
    "如需修改已写内容（更正、调整顺序），用 outbox_rewrite 整体重写。",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要追加到待发送文档的文本（演绎/NPC台词/裁决），必填，不能为空"},
        },
        "required": ["content"],
    },
)
async def outbox_append(ctx: ToolContext, content: str) -> str:
    if not content or not content.strip():
        return "错误：outbox_append 的 content 不能为空。把要发给玩家的文本放进 content 参数。"
    ctx.outbox = (ctx.outbox + "\n" + content).strip()
    return f"已写入待发送文档（追加 {len(content)} 字，当前共 {len(ctx.outbox)} 字）"


@tool(
    "outbox_rewrite",
    "【可选】整体重写待发送文档（outbox）的内容。"
    "用于修改本轮已写的内容（更正、调整、精简）；重写后文档仅保留本参数内容。"
    "文档会在 turn 结束时统一自动发送给玩家。",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "重写后的完整文档文本，必填，不能为空"},
        },
        "required": ["content"],
    },
)
async def outbox_rewrite(ctx: ToolContext, content: str) -> str:
    if not content or not content.strip():
        return "错误：outbox_rewrite 的 content 不能为空。把重写后的完整文本放进 content 参数。"
    ctx.outbox = content.strip()
    return f"已重写待发送文档（当前共 {len(ctx.outbox)} 字）"


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
         "owner_openid": ctx.member_openid, "color": hue},
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
            f"✓ 初始情景：{scene[0].get('name', scene_slug)}"
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
    ctx.store.write("npcs", slug, {"name": name, "identity": identity, "nature": "支撑剧情"}, body)
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
    ctx.store.write("items", slug, {"name": name, "nature": "支撑剧情"}, f"## {name}\n\n{description}\n")
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
    ctx.store.write("scenes", slug, {"name": name, "nature": "支撑剧情 / 可回收", "location": location}, body)
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
    ctx.store.write("locations", slug, {"name": name}, f"## {name}\n\n{description}\n")
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
    ctx.store.write("state-records", name, {"date": date, "title": title, "type": change_type}, body)
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
        # 情景与弧光：只返回最新 3 条事件，避免正文过长
        if kind in ("scenes", "story-arcs"):
            events = _extract_recent_events(body)
            if events:
                body = "…\n\n📜 最新事件（3 条）：\n" + "\n".join(events)
            else:
                body = body[:500] + ("…" if len(body) > 500 else "")
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


# --- 角色情景查询 -----------------------------------------------------------

@tool(
    "query_character_scene",
    "查询角色当前所在的地点与情景详情。返回：地点名称、情景名称与时间、"
    "同场角色与 NPC、角色自身当前状态、最新 3 条事件推进。"
    "当玩家说「我在哪」「现在什么情况」时调用。裁决角色行动前也应先调用此工具。"
    "（查角色自身信息用 query_memory(kind=\"characters\")）",
    {
        "type": "object",
        "properties": {
            "char_slug": {
                "type": "string",
                "description": "角色或 NPC slug（必填）",
            },
        },
        "required": ["char_slug"],
    },
)
async def query_character_scene(ctx: ToolContext, char_slug: str) -> str:
    d = ctx.store.read("characters", char_slug) or ctx.store.read("npcs", char_slug)
    if d is None:
        return f"错误：角色 '{char_slug}' 不存在。"

    meta, _ = d
    char_name = meta.get("name", char_slug)

    scene_slug = (
        ctx.store.char_current_scene(char_slug)
        or ctx.store.npc_current_scene(char_slug)
    )
    if not scene_slug:
        scene_slug = ctx.store.char_scene(ctx.group_id, char_slug)
    if not scene_slug:
        return f"{char_name}（{char_slug}）当前无情景归属。"

    sd = ctx.store.read("scenes", scene_slug)
    if sd is None:
        return f"{char_name} 归属于情景 {scene_slug}，但情景档案不存在。"

    scene_meta, scene_body = sd
    scene_name = scene_meta.get("name", scene_slug)
    scene_time = scene_meta.get("time", "未知时间")

    lines: list[str] = []
    # 地点
    loc_slug = scene_meta.get("location")
    if loc_slug:
        loc_name = ctx.store.location_name(loc_slug)
        if loc_name:
            lines.append(f"📍 地点：{loc_name}（{loc_slug}）")
        else:
            lines.append(f"📍 地点：{loc_slug}（档案缺失）")
    else:
        lines.append("📍 地点：未设定")

    lines.append(f"🎬 当前情景：{scene_name}（{scene_slug}）| 时间：{scene_time}")

    # 同场
    chars, npcs = ctx.store.who_in_scene(scene_slug)
    others = [c for c in chars if c != char_slug] + npcs
    if others:
        other_names: list[str] = []
        for a in others:
            ad = ctx.store.read("characters", a) or ctx.store.read("npcs", a)
            other_names.append(ad[0].get("name", a) if ad else a)
        lines.append(f"👥 同场：{'、'.join(other_names)}")
    else:
        lines.append("👥 同场：无其他角色")

    # 角色自身当前状态
    char_status = meta.get("current_status", "")
    char_equip = meta.get("equipment", [])
    if char_status or char_equip:
        status_line = f"🎭 自身：{char_status}" if char_status else ""
        if char_equip:
            equip_str = "、".join(char_equip) if isinstance(char_equip, list) else str(char_equip)
            status_line += f"；持有：{equip_str}"
        lines.append(status_line)

    # 最新 3 条事件
    events = _extract_recent_events(scene_body)
    if events:
        lines.append("📜 最近事件（最新 3 条）：")
        for ev in events:
            lines.append(f"  {ev}")
    else:
        lines.append("📜 最近事件：（暂无记录）")

    return "\n".join(lines)


# --- 情景查询 ---------------------------------------------------------------

@tool(
    "query_scene",
    "查询某个情景的完整状态。返回：地点、情景名称与时间、"
    "在场角色（含各自当前状态与装备）与 NPC 列表、最新 3 条事件推进。"
    "用于了解非当前角色所在情景的状况，或 GM 需要查看某情景详情时。",
    {
        "type": "object",
        "properties": {
            "scene_slug": {
                "type": "string",
                "description": "情景 slug（必填）",
            },
        },
        "required": ["scene_slug"],
    },
)
async def query_scene(ctx: ToolContext, scene_slug: str) -> str:
    d = ctx.store.read("scenes", scene_slug)
    if d is None:
        return f"错误：情景 '{scene_slug}' 不存在。"

    scene_meta, scene_body = d
    scene_name = scene_meta.get("name", scene_slug)
    scene_time = scene_meta.get("time", "未知时间")

    lines = [f"🎬 {scene_name}（{scene_slug}）| 时间：{scene_time}"]

    # 地点
    loc_slug = scene_meta.get("location")
    if loc_slug:
        loc_name = ctx.store.location_name(loc_slug)
        if loc_name:
            lines.append(f"📍 地点：{loc_name}（{loc_slug}）")
        else:
            lines.append(f"📍 地点：{loc_slug}（档案缺失）")
    else:
        lines.append("📍 地点：未设定")

    # 在场者
    chars, npcs = ctx.store.who_in_scene(scene_slug)
    if not chars and not npcs:
        lines.append("👥 在场：无角色或 NPC")
    else:
        present: list[str] = []
        for a in chars:
            ad = ctx.store.read("characters", a) or ctx.store.read("npcs", a)
            if ad:
                ameta = ad[0]
                a_name = ameta.get("name", a)
                a_status = ameta.get("current_status", "")
                a_equip = ameta.get("equipment", [])
                entry = a_name
                if a_status:
                    entry += f"（{a_status}）"
                if a_equip:
                    equip_str = "、".join(a_equip) if isinstance(a_equip, list) else str(a_equip)
                    entry += f" [持有：{equip_str}]"
                present.append(entry)
            else:
                present.append(a)
        for a in npcs:
            ad = ctx.store.read("npcs", a)
            if ad:
                present.append(ad[0].get("name", a))
            else:
                present.append(a)
        lines.append(f"👥 在场（{len(present)} 人）：{'、'.join(present)}")

    # 最新 3 条事件
    events = _extract_recent_events(scene_body)
    if events:
        lines.append("📜 最近事件（最新 3 条）：")
        for ev in events:
            lines.append(f"  {ev}")
    else:
        lines.append("📜 最近事件：（暂无记录）")

    return "\n".join(lines)


def _extract_recent_events(body: str, max_events: int = 3) -> list[str]:
    """从情景正文提取最近 N 条事件推进条目。"""
    for marker in ("## 事件推进", "## 对话与行动记录"):
        if marker in body:
            idx = body.rindex(marker)
            tail = body[idx + len(marker):]
            items: list[str] = []
            for line in tail.split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith(">"):
                    continue
                if stripped.startswith("#"):
                    continue
                items.append(stripped)
            return items[-max_events:] if len(items) > max_events else items
    return []


# --- 骰子工具 ---------------------------------------------------------------

@tool(
    "roll_dice",
    "掷骰子工具。接受 dicelet 骰子表达式（如 2d6+3、4d6k3、d20+5、3#6d6），返回掷骰结果。"
    "用于 TRPG 中的随机裁决：属性检定、技能判定、战斗伤害、随机事件、运气判定等。"
    "你应在裁决玩家行动需要随机性时调用此工具，不要自己编造掷骰结果。"
    "掷骰日志会自动追加到待发送文档，玩家可见具体骰值，无需再手动把数值写进 outbox_append。",
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
    except Exception as e:
        return f"掷骰错误：{e}"

    # 掷骰日志自动追加到待发送文档，随 turn 结束统一发送给玩家
    ctx.outbox = (ctx.outbox + f"\n🎲 掷骰 {expression} → {result.full}").strip()
    return result.full


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
