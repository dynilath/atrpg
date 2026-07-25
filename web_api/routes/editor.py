"""editor.py — /api/editor/* 路由。

LLM 辅助的备团编辑 API：通过对话式交互创建/修改游戏素材。
所有写操作走 LLM 生成 + 用户确认 → store 落盘流程。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import get_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/editor", tags=["editor"])

# 编辑助手 system prompt 缓存
_EDITOR_RUNTIME: str | None = None


def _load_editor_runtime() -> str:
    global _EDITOR_RUNTIME
    if _EDITOR_RUNTIME is None:
        p = Path(__file__).resolve().parent.parent.parent / "bot" / "atrpg_gm" / "editor_runtime.md"
        _EDITOR_RUNTIME = p.read_text(encoding="utf-8")
    return _EDITOR_RUNTIME


def _load_template(kind: str) -> str:
    """读取对应类型的模板文件，供 LLM 参考结构。"""
    tpl_map = {
        "story-arcs": "story-arc.md",
        "characters": "character.md",
        "npcs": "character.md",
        "items": None,
        "scenes": "scene.md",
        "locations": None,
    }
    tpl = tpl_map.get(kind)
    if not tpl:
        return ""
    p = Path(__file__).resolve().parent.parent.parent / "templates" / tpl
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


async def _llm_generate(
    system_prompt: str,
    user_prompt: str,
    existing_summary: str = "",
) -> str:
    """调 LLM 生成内容（纯文本，无工具调用）。

    返回 LLM 的完整回复文本。
    """
    from bot.atrpg_gm.llm import chat
    return await chat(system_prompt, user_prompt)


async def _llm_generate_structured(
    kind: str,
    user_prompt: str,
    store: Any,
) -> dict[str, Any] | None:
    """调 LLM 生成结构化文档内容。

    流程：
    1. 读取已有数据摘要（避免冲突）
    2. 读取模板（指导输出结构）
    3. 构造 system + user prompt
    4. 调 LLM 生成
    5. 解析 frontmatter + body
    6. 返回 {slug, meta, body, title}
    """
    runtime = _load_editor_runtime()

    # 已有数据摘要
    existing_docs = store.list_docs(kind)
    existing_summary_lines = [f"已有 {len(existing_docs)} 条："]
    for d in existing_docs[:20]:  # 最多展示 20 条
        name = d["meta"].get("名称") or d["meta"].get("姓名") or d["slug"]
        extra = d["meta"].get("级别") or d["meta"].get("身份") or ""
        existing_summary_lines.append(f"- {d['slug']}: {name}" + (f" ({extra})" if extra else ""))
    existing_summary = "\n".join(existing_summary_lines)

    # 模板参考
    template_str = _load_template(kind)
    template_hint = f"\n请参考以下模板结构生成内容：\n\n{template_str}\n" if template_str else ""

    system_prompt = (
        f"{runtime}\n\n"
        f"## 当前任务\n\n"
        f"你正在帮用户创建/编辑 {kind} 类型的素材。\n"
        f"{existing_summary}\n"
        f"{template_hint}"
        f"\n## 输出格式（必须遵守）\n\n"
        f"你必须严格按以下格式输出，用 --- 分隔 YAML frontmatter 和 Markdown 正文：\n\n"
        f"---\n"
        f"slug: <唯一英文slug，小写连字符格式，如 dock-workers-strike>\n"
        f"名称: <中文名称>\n"
        f"<其他YAML元数据字段，每行一个键值对>\n"
        f"---\n"
        f"\n"
        f"<Markdown 正文内容>\n"
        f"\n"
        f"务必包含 slug 字段，使用简短英文。不要用中文做 slug。\n"
    )

    full_response = await _llm_generate(system_prompt, user_prompt)

    # 解析 frontmatter + body
    from bot.atrpg_gm.store import _parse_doc, slugify
    meta, body = _parse_doc(full_response)
    if not meta or not meta.get("slug"):
        # LLM 没按格式输出，尝试从纯文本提取
        title = user_prompt[:60].strip()
        slug = slugify(title)
        return {"slug": slug, "meta": {"slug": slug, "名称": title}, "body": full_response, "title": title}

    title = meta.get("名称") or meta.get("姓名") or meta.get("标题") or slugify(user_prompt[:30])
    slug = meta.get("slug") or slugify(title)

    return {"slug": slug, "meta": meta, "body": body, "title": title}


def _json_safe(obj: Any) -> Any:
    """递归将不可 JSON 序列化的类型（如 datetime.date）转为字符串。"""
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


# ── 弧光 ──

@router.get("/arcs")
async def list_arcs():
    """列出所有弧光。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("story-arcs")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/arcs")
async def create_arc(body: dict[str, Any]):
    """LLM 辅助新建弧光。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("story-arcs", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        # 补全弧光特有字段
        meta = result["meta"]
        meta.setdefault("级别", "单局")
        meta.setdefault("规划者", "备团用户")
        meta.setdefault("来源", "备团编辑")
        meta.setdefault("当前阶段", "启程")
        meta.setdefault("状态", "草案")
        p = s.write("story-arcs", result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建弧光: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/arcs/{slug}")
async def get_arc(slug: str):
    """弧光详情。"""
    try:
        s = get_store()
        d = s.read("story-arcs", slug)
        if d is None:
            return JSONResponse({"error": "不存在"}, status_code=404)
        return JSONResponse({"meta": d[0], "body": d[1]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/arcs/{slug}")
async def update_arc(slug: str, body: dict[str, Any]):
    """LLM 辅助修改弧光。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        existing = s.read("story-arcs", slug)
        if existing is None:
            return JSONResponse({"error": f"弧光 {slug} 不存在"}, status_code=404)

        runtime = _load_editor_runtime()
        meta, content = existing
        existing_text = f"## 当前内容\n\n元数据：{json.dumps(meta, ensure_ascii=False)}\n\n{content}"
        user_prompt = f"{existing_text}\n\n## 修改要求\n\n{prompt}"
        system_prompt = f"{runtime}\n\n请修改上述文档。保持 --- frontmatter --- 格式。只改修改要求涉及的部分，其余保持原样。"
        full_response = await _llm_generate(system_prompt, user_prompt)

        from bot.atrpg_gm.store import _parse_doc
        new_meta, new_body = _parse_doc(full_response)
        if new_meta:
            # 保留原有 slug 和 created
            new_meta.setdefault("slug", slug)
            s.write("story-arcs", slug, new_meta, new_body)
            logger.info(f"编辑助手修改弧光: {slug}")
            return JSONResponse({"ok": True, "slug": slug})
        return JSONResponse({"error": "LLM 输出格式不符"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 角色/NPC ──

@router.get("/characters")
async def list_characters():
    """列出所有角色（含 NPC）。"""
    try:
        s = get_store()
        chars = s.list_docs("characters")
        npcs = s.list_docs("npcs")
        return JSONResponse({"characters": _json_safe(chars), "npcs": _json_safe(npcs)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/characters")
async def create_character(body: dict[str, Any]):
    """LLM 辅助新建角色（玩家角色或 NPC）。"""
    prompt = body.get("prompt", "").strip()
    char_type = body.get("type", "npc")  # "pc" 或 "npc"
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        kind = "characters" if char_type == "pc" else "npcs"
        result = await _llm_generate_structured(kind, prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        meta = result["meta"]
        meta.setdefault("类型", "玩家角色" if char_type == "pc" else "NPC")
        meta.setdefault("状态", "正式" if char_type == "npc" else "待确认")
        p = s.write(kind, result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建{kind}: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "kind": kind,
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 物品 ──

@router.get("/items")
async def list_items():
    """列出所有物品。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("items")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/items")
async def create_item(body: dict[str, Any]):
    """LLM 辅助新建物品。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("items", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        meta = result["meta"]
        meta.setdefault("性质", "支撑剧情")
        p = s.write("items", result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建物品: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 场景 ──

@router.get("/scenes")
async def list_scenes():
    """列出所有场景。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("scenes")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/scenes")
async def create_scene(body: dict[str, Any]):
    """LLM 辅助新建场景。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("scenes", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        meta = result["meta"]
        meta.setdefault("性质", "支撑剧情 / 可回收")
        meta.setdefault("在场者", [])
        p = s.write("scenes", result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建场景: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── 地点 ──

@router.get("/locations")
async def list_locations():
    """列出所有地点。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("locations")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/locations")
async def create_location(body: dict[str, Any]):
    """LLM 辅助新建地点。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("locations", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        p = s.write("locations", result["slug"], result["meta"], result["body"])
        logger.info(f"编辑助手创建地点: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
