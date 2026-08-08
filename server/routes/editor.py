"""editor.py --- /api/editor/* 路由。

LLM 辅助的备团编辑 API：通过对话式交互创建/修改游戏素材。
所有写操作走 LLM 生成 + 用户确认 -> store 落盘流程。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from server.deps import get_store
from core.llm import chat, _client_for, completion_kwargs
from core.config import resolve_editor_profile
from core.store import _parse_doc, slugify
from core.editor_tools import dispatch as dispatch_editor_tool
from core.editor_skills import (
    build_skill_system_prompt,
    get_chat_tools,
    KIND_LABELS,
    KIND_TO_SKILL,
)
from core.doc_analysis import build_index as build_upload_index, index_summary as upload_index_summary
from .file_parser import parse_to_txt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/editor", tags=["editor"])

# 编辑助手 system prompt 缓存
_EDITOR_RUNTIME: str | None = None

# 工具使用说明（注入 system prompt）
_EDITOR_TOOL_INSTRUCTIONS = """
## 编辑工具

你现在可以调用以下工具来**直接操作游戏文件**，而不只是生成文本：

### 核心编辑
- `read_doc` — 读取文件（返回解析后的 meta + body + 自动校验结果）。修改文件前请先读取。
- `write_doc` — 创建新文件或覆盖已有文件。提供 kind/slug/meta/body。
- `patch_meta` — **修改 front matter 字段（推荐）**。只传要改的字段，其余保持不变。不可改 slug/updated。
- `patch_body` — 在 Markdown 正文中精确插入/替换/删除（按标题定位，如 "## 基础信息"）。
- `search_docs` — 跨文件搜索（文本关键词 + 元数据过滤）。

### Front Matter 规范化
- `validate_doc` — 按类型 schema 校验单个文件的 front matter。
- `normalize_doc` — 自动修复（补全默认值、修正枚举值、从正文提取信息）。默认清理冗余 slug。
- `validate_all` — 批量校验整个项目，生成报告。
- `normalize_all` — 批量自动修复。默认 dry_run=true（先预览），确认后设 dry_run=false 执行。

### 辅助
- `list_docs` — 列出文件（含关键字段摘要）。
- `delete_doc` — 删除文件（不可逆，谨慎）。
- `rename_doc` — 重命名文件（自动更新其他文件中的引用）。

### 上传文档分析（渐进式披露）
用户上传的参考文档（PDF/DOC，解析后存 .atrpg/uploads/*.txt）**不会全文注入**，
system prompt 中只有轻量索引（文件名/字符数/章节/预览）。需要细节时按需调用：
- `read_upload` — 读取文档片段（offset/length 或 section 章节定位），**不要整篇读**。
- `search_upload` — 关键词检索，返回命中片段与位置。
- `analyze_upload` — 让独立分析会话消化整篇文档，报告落盘 .analysis.md，不占主对话上下文。
  适合「根据这份设定集生成素材」类需要整体理解的场景。
- 索引里未出现的文件名，先 `search_upload` 确认 txt 名。

### 工具使用原则
1. **优先使用精确工具**：改一个字段用 `patch_meta`，不要 `write_doc` 重写整个文件。
2. **写入前先读取**：修改文件前先 `read_doc` 了解当前内容。
3. **批量操作先预览**：`normalize_all` 先用 `dry_run=true`。
4. **创建新文件用 `write_doc`**：你需要提供完整的 meta 字典和 Markdown body。
5. **校验反馈已自动提供**：`read_doc`、`write_doc`、`patch_meta` 返回时已自动包含 validation 结果。
6. **slug 是文件名**：不要尝试通过 `patch_meta` 修改 slug，改名请用 `rename_doc`。
"""


def _load_editor_runtime() -> str:
    global _EDITOR_RUNTIME
    if _EDITOR_RUNTIME is None:
        p = Path(__file__).resolve().parent.parent.parent / "core" / "editor_runtime.md"
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
        "terminology": "terminology.md",
    }
    tpl = tpl_map.get(kind)
    if not tpl:
        return ""
    p = Path(__file__).resolve().parent.parent.parent / "templates" / tpl
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _editor_workflow_for(kind: str) -> str:
    """将内容类型映射为 editor workflow key，用于 resolve_editor_profile。

    kind (如 "story-arcs") → editor workflow key (如 "story_arc")
    """
    _KIND_TO_EWF: dict[str, str] = {
        "story-arcs": "story_arc",
        "characters": "character",
        "npcs": "npc",
        "items": "item",
        "scenes": "scene",
        "locations": "location",
        "terminology": "terminology",
        "state-records": "state_record",
    }
    return _KIND_TO_EWF.get(kind, "chat")


async def _llm_generate(
    system_prompt: str,
    user_prompt: str,
    existing_summary: str = "",
    workflow: str = "chat",
) -> str:
    """调 LLM 生成内容（纯文本，无工具调用）。

    返回 LLM 的完整回复文本。
    workflow: 工作场景名（默认 chat），可传入 editor workflow key。
    """
    return await chat(system_prompt, user_prompt, workflow=workflow)


async def _llm_generate_structured(
    kind: str,
    user_prompt: str,
    store: Any,
) -> dict[str, Any] | None:
    """调 LLM 生成结构化文档内容（使用 skill 系统）。

    流程：
    1. 加载对应 content type 的 skill（含专属 identity + 模板）
    2. 读取已有数据摘要（避免冲突）
    3. 构造 system + user prompt
    4. 调 LLM 生成
    5. 解析 frontmatter + body
    6. 返回 {slug, meta, body, title}
    """
    # 已有数据摘要
    existing_docs = store.list_docs(kind)
    existing_summary_lines = [f"已有 {len(existing_docs)} 条："]
    for d in existing_docs[:20]:  # 最多展示 20 条
        name = d["meta"].get("name") or d["slug"]
        extra = d["meta"].get("level") or d["meta"].get("identity") or ""
        existing_summary_lines.append(f"- {d['slug']}: {name}" + (f" ({extra})" if extra else ""))
    existing_summary = "\n".join(existing_summary_lines)

    # 使用 skill 系统构建专属 system prompt（含 identity + 模板 + 已有数据）
    system_prompt = build_skill_system_prompt(kind, existing_summary=existing_summary)

    # 如果 skill 未找到，回退到通用 editor_runtime
    if not system_prompt:
        system_prompt = _load_editor_runtime()
        template_str = _load_template(kind)
        if template_str:
            system_prompt += f"\n\n## 模板参考\n\n{template_str}"
        system_prompt += f"\n\n## 已有内容\n\n{existing_summary}"

    kind_label = KIND_LABELS.get(kind, kind)
    system_prompt += (
        f"\n\n## 当前任务\n\n"
        f"你正在帮用户创建 {kind_label} 类型的素材。\n"
        f"\n## 输出格式（必须遵守）\n\n"
        f"你必须严格按以下格式输出，用 --- 分隔 YAML frontmatter 和 Markdown 正文：\n\n"
        f"---\n"
        f"<YAML 元数据字段，使用英文字段名，每行一个键值对>\n"
        f"---\n"
        f"\n"
        f"<Markdown 正文内容>\n"
        f"\n"
        f"不要写 slug 或 updated 字段，这些由系统自动处理。\n"
    )

    full_response = await _llm_generate(
        system_prompt, user_prompt, workflow=_editor_workflow_for(kind)
    )

    # 解析 frontmatter + body
    meta, body = _parse_doc(full_response)

    # 从 AI 输出中提取名称并生成 slug（忽略 AI 提供的 slug，系统自动处理）
    title = (
        meta.get("name") or meta.get("title")
        or slugify(user_prompt[:60])
    )
    slug = slugify(title)

    # 清理 AI 不应填的字段
    meta.pop("slug", None)
    meta.pop("updated", None)

    if not meta:
        return {"slug": slug, "meta": {"name": title}, "body": full_response, "title": title}

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


# --- 弧光 ---

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
        meta.setdefault("level", "单局")
        meta.setdefault("planner", "备团用户")
        meta.setdefault("source", "备团编辑")
        meta.setdefault("current_stage", "启程")
        meta.setdefault("status", "草案")
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


# --- 角色/NPC ---

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
        meta.setdefault("type", "玩家角色" if char_type == "pc" else "NPC")
        meta.setdefault("status", "正式" if char_type == "npc" else "待确认")
        # PC 自动分配颜色
        if char_type == "pc" and "color" not in meta:
            from core.store import char_color
            meta["color"] = char_color(meta.get("name", result["slug"]))
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


# --- 物品 ---

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
        meta.setdefault("nature", "支撑剧情")
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


# --- 情景 ---

@router.get("/scenes")
async def list_scenes():
    """列出所有情景。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("scenes")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/scenes")
async def create_scene(body: dict[str, Any]):
    """LLM 辅助新建情景。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("scenes", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        meta = result["meta"]
        meta.setdefault("nature", "支撑剧情 / 可回收")
        p = s.write("scenes", result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建情景: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- 地点 ---

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


# --- 设定术语 ---

@router.get("/terminology")
async def list_terminology():
    """列出所有设定术语。"""
    try:
        s = get_store()
        return JSONResponse(_json_safe(s.list_docs("terminology")))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/terminology")
async def create_terminology(body: dict[str, Any]):
    """LLM 辅助新建设定术语。"""
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt 不能为空"}, status_code=400)
    try:
        s = get_store()
        result = await _llm_generate_structured("terminology", prompt, s)
        if not result:
            return JSONResponse({"error": "LLM 生成失败"}, status_code=500)
        meta = result["meta"]
        meta.setdefault("category", "其他")
        p = s.write("terminology", result["slug"], meta, result["body"])
        logger.info(f"编辑助手创建术语: {result['slug']}")
        return JSONResponse({
            "ok": True,
            "slug": result["slug"],
            "title": result["title"],
            "path": str(p),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ===========================================================================
# 编辑器 AI 助手聊天（持久化，多轮对话）
# ===========================================================================

def _editor_chat_path(game_root: str | Path) -> Path:
    return Path(game_root) / ".atrpg" / "editor_chat.json"


def _load_editor_chat(game_root: str | Path) -> list[dict]:
    p = _editor_chat_path(game_root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_editor_chat(game_root: str | Path, messages: list[dict]):
    p = _editor_chat_path(game_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/chat")
async def editor_chat(body: dict[str, Any]):
    """编辑器 AI 助手对话----多轮，持久化到 .atrpg/editor_chat.json。"""
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message 不能为空"}, status_code=400)

    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    history = _load_editor_chat(s.root)

    runtime = _load_editor_runtime()
    existing = _build_existing_summary(s)
    # 上传文档只注入轻量索引（渐进式披露），全文按需经 read_upload/search_upload/analyze_upload 获取
    upload_summary = upload_index_summary(Path(s.root) / ".atrpg" / "uploads")

    system_content = f"{runtime}\n\n{_EDITOR_TOOL_INSTRUCTIONS}\n\n## 已有内容概况\n\n{existing}"
    if upload_summary:
        system_content += f"\n\n{upload_summary}"

    llm_messages = [
        {"role": "system", "content": system_content}
    ] + history[-30:] + [
        {"role": "user", "content": message}
    ]

    from core.llm import _client_for, completion_kwargs, resolve_profile
    profile = resolve_profile("chat")
    req_kwargs = completion_kwargs(profile)

    # 保存 user 消息
    history.append({"role": "user", "content": message})

    reply_parts: list[str] = []
    try:
        # ---- Tool-calling 循环 ----
        max_tool_rounds = 15
        for _ in range(max_tool_rounds):
            resp = await _client_for(profile).chat.completions.create(
                model=profile.model,
                messages=llm_messages,
                tools=get_chat_tools(),
                tool_choice="auto",
                **req_kwargs,
            )
            msg = resp.choices[0].message

            # 如果 LLM 返回了文本回复
            if msg.content:
                reply_parts.append(msg.content)

            # 如果没有 tool calls，结束循环
            if not msg.tool_calls:
                llm_messages.append({"role": "assistant", "content": msg.content or ""})
                break

            # 执行 tool calls
            llm_messages.append({
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                tool_result = await dispatch_editor_tool(s, tc)
                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

        reply = "\n\n".join(reply_parts)
        if not reply and not msg.tool_calls:
            reply = "(未生成回复)"

    except Exception as e:
        logger.exception("编辑器聊天 LLM 调用失败")
        return JSONResponse({"error": f"LLM 调用失败: {e}"}, status_code=500)

    # 保存 assistant 消息到历史（简化版：只保存文本，不保存 tool_calls 细节）
    history.append({"role": "assistant", "content": reply or "(已执行工具操作)"})
    _save_editor_chat(s.root, history)

    logger.info(f"编辑器聊天: user_msg={message[:40]!r} reply_len={len(reply)}")
    return JSONResponse({"reply": reply})


@router.get("/chat")
async def get_editor_chat():
    """获取编辑器 AI 助手的历史对话。"""
    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    history = _load_editor_chat(s.root)
    return JSONResponse({"messages": history})


def _build_existing_summary(s) -> str:
    """构建已有内容摘要，供编辑器 AI 参考。"""
    kinds = ["story-arcs", "characters", "npcs", "items", "scenes", "locations", "terminology"]
    lines = []
    for kind in kinds:
        docs = s.list_docs(kind)
        if docs:
            lines.append(f"\n### {kind} ({len(docs)} 条)")
            for d in docs[:10]:
                name = d["meta"].get("name") or d["meta"].get("term") or d["slug"]
                extra = d["meta"].get("level") or d["meta"].get("identity") or d["meta"].get("category") or ""
                lines.append(f"- {d['slug']}: {name}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines) if lines else "暂无已有内容"


# ---------------------------------------------------------------------------
# 文件上传（.atrpg/uploads/）
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_UPLOAD_MB = 50


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传 PDF/DOC 参考材料到 .atrpg/uploads/。

    返回 {ok, filename, size, path}。
    """
    if not file.filename:
        return JSONResponse({"error": "文件名为空"}, status_code=400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"error": f"不支持的文件类型（允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}）"},
            status_code=400,
        )

    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    upload_dir = Path(s.root) / ".atrpg" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 防止文件名冲突：加时间戳前缀
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{ts}_{file.filename}"
    dest = upload_dir / safe_name

    # 分块读取写入，避免超大文件撑爆内存
    size = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    f.close()
                    dest.unlink(missing_ok=True)
                    return JSONResponse(
                        {"error": f"文件超过最大允许大小（{MAX_UPLOAD_MB}MB）"},
                        status_code=413,
                    )
                f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    logger.info(f"编辑器上传: {safe_name} ({size} bytes) -> .atrpg/uploads/")

    # 自动解析为 txt
    txt_path = parse_to_txt(dest)
    parsed = bool(txt_path)

    # 刷新上传文档索引（轻量，供编辑助手上下文注入）
    try:
        build_upload_index(upload_dir)
    except Exception:
        logger.warning("编辑器上传后刷新文档索引失败", exc_info=True)

    return JSONResponse({
        "ok": True,
        "filename": safe_name,
        "original_name": file.filename,
        "size": size,
        "path": str(dest),
        "uploaded_at": ts,
        "parsed": parsed,
        "txt_path": str(txt_path) if txt_path else None,
    })


@router.get("/uploads")
async def list_uploads():
    """列出 .atrpg/uploads/ 中已上传的参考文件。"""
    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    upload_dir = Path(s.root) / ".atrpg" / "uploads"
    if not upload_dir.exists():
        return JSONResponse({"files": []})

    files = []
    for p in sorted(upload_dir.iterdir(), reverse=True):
        if p.is_file() and p.suffix.lower() not in (".txt",):  # 排除解析产物
            stat = p.stat()
            parsed = p.with_suffix(".txt").exists()
            files.append({
                "filename": p.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "parsed": parsed,
            })

    return JSONResponse({"files": files})


@router.delete("/uploads/{filename}")
async def delete_upload(filename: str):
    """删除 .atrpg/uploads/ 中的指定文件。"""
    try:
        s = get_store()
    except Exception as e:
        return JSONResponse({"error": f"Store 未就绪: {e}"}, status_code=500)

    upload_dir = Path(s.root) / ".atrpg" / "uploads"
    dest = upload_dir / filename

    # 防止路径穿越攻击
    resolved = dest.resolve()
    if not str(resolved).startswith(str(upload_dir.resolve())):
        return JSONResponse({"error": "非法文件路径"}, status_code=400)

    if not dest.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)

    dest.unlink()
    # 同时删除关联的解析 txt
    txt = dest.with_suffix(".txt")
    if txt.exists():
        txt.unlink()
    # 同时删除关联的分析报告
    analysis = dest.with_suffix(".analysis.md")
    if analysis.exists():
        analysis.unlink()
    # 刷新索引
    try:
        build_upload_index(upload_dir)
    except Exception:
        logger.warning("编辑器删除后刷新文档索引失败", exc_info=True)
    logger.info(f"编辑器删除上传文件: {filename}")
    return JSONResponse({"ok": True})
