"""editor_tools.py --- AI 辅助编辑工具注册表。

提供 12 个工具供编辑器 LLM 调用：核心编辑、front matter 规范化、辅助操作。
复用 tools.py 的 @tool 注册模式，独立注册表避免与 GM 工具冲突。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from . import schemas, schema_validator, schema_normalizer, store as store_mod

logger = logging.getLogger(__name__)


# ===========================================================================
# 工具注册表
# ===========================================================================

@dataclass
class EditorToolDef:
    schema: dict[str, Any]
    func: Callable[..., Awaitable[str]]


_EDITOR_REGISTRY: dict[str, EditorToolDef] = {}


def editor_tool(name: str, description: str, params: dict[str, Any]):
    """注册编辑器工具。"""
    def deco(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": params,
            },
        }
        _EDITOR_REGISTRY[name] = EditorToolDef(schema=schema, func=func)
        return func
    return deco


def editor_tool_schemas() -> list[dict[str, Any]]:
    """返回所有编辑器工具的 OpenAI function schema 列表。"""
    return [td.schema for td in _EDITOR_REGISTRY.values()]


async def dispatch(store: store_mod.Store, call) -> str:
    """执行编辑器工具调用。

    Args:
        store: Store 实例
        call: OpenAI tool call 对象（含 name 和 arguments）

    Returns:
        工具执行结果字符串（供 LLM 阅读）
    """
    td = _EDITOR_REGISTRY.get(call.name)
    if td is None:
        return f"错误：未知编辑器工具 '{call.name}'"

    try:
        args = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
        return await td.func(store, **args)
    except json.JSONDecodeError:
        return f"错误：工具 '{call.name}' 的参数不是合法 JSON"
    except TypeError as e:
        return f"错误：工具 '{call.name}' 参数不匹配：{e}"
    except Exception:
        logger.warning(f"编辑器工具 {call.name} 执行异常", exc_info=True)
        return f"错误：执行 {call.name} 时发生内部错误"


# ===========================================================================
# 辅助函数
# ===========================================================================

VALID_KINDS = (
    "characters", "npcs", "scenes", "locations", "items",
    "story-arcs", "state-records", "terminology",
)


def _summarize_issues(result) -> str:
    """格式化校验结果为可读文本。"""
    parts = []
    if result.errors:
        parts.append(f"  ❌ 错误 ({len(result.errors)}):")
        for e in result.errors:
            parts.append(f"    - {e.field}: {e.message}")
    if result.warnings:
        parts.append(f"  ⚠️ 警告 ({len(result.warnings)}):")
        for w in result.warnings:
            parts.append(f"    - {w.field}: {w.message}")
    if result.info:
        parts.append(f"  ℹ️ 提示 ({len(result.info)}):")
        for i in result.info:
            parts.append(f"    - {i.field}: {i.message}")
    return "\n".join(parts) if parts else "  ✅ 无问题"


# ===========================================================================
# A 类：核心编辑工具
# ===========================================================================

@editor_tool(
    "read_doc",
    "读取一个文档文件，返回解析后的 front matter（meta 字典）+ Markdown 正文（body 字符串）+ 自动校验反馈。"
    "可选附带关联文件摘要（如角色所在情景、弧光关联的 NPC 等）。"
    "这是了解文件内容的入口——修改文件前请先 read_doc。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "slug": {
                "type": "string",
                "description": "文档 slug（文件名去掉 .md）",
            },
            "include_related": {
                "type": "boolean",
                "description": "是否附带关联文件摘要（默认 false）",
            },
        },
        "required": ["kind", "slug"],
    },
)
async def read_doc(store: store_mod.Store, kind: str, slug: str, include_related: bool = False) -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。可用 search_docs 或 list_docs 查找。"
    meta, body = d

    # 校验
    vr = schema_validator.validate(meta, kind, store)

    # 关联信息
    related_str = ""
    if include_related:
        related_parts = []
        # 角色 → 所在情景
        if kind == "characters":
            cs = meta.get("current_location")
            if cs:
                sd = store.read("scenes", cs)
                related_parts.append(f"当前情景: {cs}" + (f" ({sd[0].get('name', cs)})" if sd else ""))
        # 情景 → 在场者 + 地点
        elif kind == "scenes":
            chars, npcs = store.who_in_scene(slug)
            if chars or npcs:
                names = []
                for c in chars:
                    cd = store.read("characters", c)
                    names.append(cd[0].get("name", c) if cd else c)
                for n in npcs:
                    nd = store.read("npcs", n)
                    names.append(nd[0].get("name", n) if nd else n)
                related_parts.append(f"在场者: {', '.join(names)}")
            loc = meta.get("location")
            if loc:
                ld = store.read("locations", loc)
                related_parts.append(f"地点: {loc}" + (f" ({ld[0].get('name', loc)})" if ld else ""))
        if related_parts:
            related_str = "\n关联信息:\n" + "\n".join(f"  - {p}" for p in related_parts)

    return json.dumps({
        "ok": True,
        "kind": kind,
        "slug": slug,
        "meta": meta,
        "body": body[:3000] + ("…" if len(body) > 3000 else ""),
        "body_length": len(body),
        "related": related_str.strip() if related_str else None,
        "validation": {
            "valid": vr.valid,
            "errors_count": len(vr.errors),
            "warnings_count": len(vr.warnings),
            "errors": [{"field": e.field, "message": e.message} for e in vr.errors],
            "warnings": [{"field": w.field, "message": w.message} for w in vr.warnings],
        },
    }, ensure_ascii=False, default=str)


@editor_tool(
    "write_doc",
    "创建新文档或全量覆盖已有文档。传入 kind/slug/meta/body。"
    "新建时 slug 可选（不填则从 meta.name 自动生成），覆盖时必须提供 slug。"
    "meta 中不要包含 slug/updated（系统自动处理）。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "slug": {
                "type": "string",
                "description": "文档 slug。新建时可省略（系统从 meta.name 自动生成）",
            },
            "meta": {
                "type": "object",
                "description": "front matter 元数据字典，至少包含 name。键名使用英文。不要传 slug/updated。",
            },
            "body": {
                "type": "string",
                "description": "Markdown 正文",
            },
            "overwrite": {
                "type": "boolean",
                "description": "是否允许覆盖已有文件（默认 true）",
            },
        },
        "required": ["kind", "meta", "body"],
    },
)
async def write_doc(store: store_mod.Store, kind: str, meta: dict, body: str,
                    slug: str = "", overwrite: bool = True) -> str:
    # 清理系统字段
    for sf in schemas.SYSTEM_FIELDS:
        meta.pop(sf, None)

    if not slug:
        name = meta.get("name", "")
        if not name:
            return "错误：未提供 slug 且 meta 中无 name 字段，无法生成文件名。"
        slug = store_mod.slugify(name)
        if not slug:
            return f"错误：无法从 name='{name}' 生成有效 slug。"

    if not overwrite and store.read(kind, slug) is not None:
        return f"错误：{kind}/{slug} 已存在。设置 overwrite=true 可覆盖。"

    p = store.write(kind, slug, meta, body)

    # 写入后校验
    vr = schema_validator.validate(meta, kind, store)

    return json.dumps({
        "ok": True,
        "kind": kind,
        "slug": slug,
        "path": str(p),
        "validation": {
            "valid": vr.valid,
            "errors_count": len(vr.errors),
            "warnings_count": len(vr.warnings),
            "errors": [{"field": e.field, "message": e.message} for e in vr.errors],
            "warnings": [{"field": w.field, "message": w.message} for w in vr.warnings],
        },
    }, ensure_ascii=False)


@editor_tool(
    "patch_meta",
    "修改文档的 front matter 字段。只传要改的字段，其余保持不变（merge patch）。"
    "可同时 set（设置/更新）和 delete（删除）字段。"
    "不可操作系统字段 slug/updated——slug 由文件名决定，请用 rename_doc 重命名。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "slug": {
                "type": "string",
                "description": "文档 slug",
            },
            "set": {
                "type": "object",
                "description": "要设置/更新的字段键值对 { field: value }。只传要改的字段。",
            },
            "delete": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要删除的字段名列表",
            },
        },
        "required": ["kind", "slug"],
    },
)
async def patch_meta(store: store_mod.Store, kind: str, slug: str,
                     set: dict[str, Any] | None = None,
                     delete: list[str] | None = None) -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。"
    meta, body = d

    set_dict = set or {}
    delete_list = delete or []
    changes: list[dict] = []

    # 系统字段保护
    for sf in schemas.SYSTEM_FIELDS:
        if sf in set_dict:
            return f"错误：不能通过 patch_meta 修改 '{sf}'。slug 是文件名（请用 rename_doc），updated 由系统自动维护。"
        if sf in delete_list:
            return f"错误：不能通过 patch_meta 删除 '{sf}'。该字段由系统管理。"

    # 设置字段
    for field, value in set_dict.items():
        old = meta.get(field)
        meta[field] = value
        changes.append({"field": field, "old": old, "new": value, "action": "set"})

    # 删除字段
    for field in delete_list:
        if field in meta:
            old = meta.pop(field)
            changes.append({"field": field, "old": old, "new": None, "action": "delete"})

    if not changes:
        return "警告：未指定任何 set 或 delete 操作，文件未修改。"

    store.write(kind, slug, meta, body)

    # 校验
    vr = schema_validator.validate(meta, kind, store)

    return json.dumps({
        "ok": True,
        "changes": changes,
        "meta": {k: v for k, v in meta.items() if k not in schemas.SYSTEM_FIELDS},
        "validation": {
            "valid": vr.valid,
            "errors": [{"field": e.field, "message": e.message} for e in vr.errors],
            "warnings": [{"field": w.field, "message": w.message} for w in vr.warnings],
        },
    }, ensure_ascii=False, default=str)


@editor_tool(
    "patch_body",
    "在文档的 Markdown 正文中精确增/删/改。使用 Markdown 标题（如 '## 基础信息'）定位操作位置。"
    "支持的操作：insert_after（在某段落后插入）、insert_before（在某段落前插入）、"
    "replace（替换某段落）、append（追加到文末）、delete（删除某段落）。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "slug": {
                "type": "string",
                "description": "文档 slug",
            },
            "operation": {
                "type": "string",
                "enum": ["insert_after", "insert_before", "replace", "append", "delete"],
                "description": "操作类型",
            },
            "target": {
                "type": "string",
                "description": "目标定位：Markdown 标题（如 '## 基础信息'）或段落锚文本。"
                "insert_after: 在目标段落后插入。"
                "insert_before: 在目标段落前插入。"
                "replace: 替换目标段落。"
                "delete: 删除目标段落。"
                "append 操作不需要 target。",
            },
            "content": {
                "type": "string",
                "description": "要插入/替换的内容（insert/replace 时必填，delete 时不需要）",
            },
        },
        "required": ["kind", "slug", "operation"],
    },
)
async def patch_body(store: store_mod.Store, kind: str, slug: str, operation: str,
                     target: str = "", content: str = "") -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。"
    meta, body = d

    if operation == "append":
        new_body = body.rstrip() + "\n\n" + content + "\n"
        store.write(kind, slug, meta, new_body)
        return json.dumps({
            "ok": True,
            "operation": "append",
            "preview": (content[:200] + "…") if len(content) > 200 else content,
        }, ensure_ascii=False)

    if not target:
        return "错误：insert_after/insert_before/replace/delete 必须提供 target。"

    # 定位 target 在 body 中的位置
    if target.startswith("#"):
        # 标题定位：找到该标题，操作范围到下一个同级标题
        idx = body.find(target)
        if idx == -1:
            return f"错误：在正文中未找到 '{target}'。可用的标题有: " + \
                   ", ".join(line.strip() for line in body.split("\n") if line.strip().startswith("##"))
        # 找到该标题行的结束
        line_end = body.find("\n", idx)
        if line_end == -1:
            line_end = len(body)
        # 找到下一个同级标题的位置
        heading_level = len(target) - len(target.lstrip("#"))
        next_heading_idx = len(body)
        rest = body[line_end + 1:]
        for line in rest.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#" * heading_level + " ") or stripped.startswith("#" * (heading_level - 1) + " "):
                nh = body.find(line, line_end + 1)
                if nh != -1:
                    next_heading_idx = nh
                    break

        target_start = idx
        target_end = next_heading_idx
        before = body[:target_start]
        target_text = body[target_start:target_end]
        after = body[target_end:]

    else:
        # 锚文本定位
        idx = body.find(target)
        if idx == -1:
            return f"错误：在正文中未找到 '{target[:60]}'。"
        # 扩展到行边界
        line_start = body.rfind("\n", 0, idx) + 1
        line_end = body.find("\n", idx + len(target))
        if line_end == -1:
            line_end = len(body)
        target_start = line_start
        target_end = line_end
        before = body[:target_start]
        target_text = body[target_start:target_end]
        after = body[target_end:]

    # 执行操作
    if operation == "insert_after":
        new_body = before + target_text + "\n" + content + after
        preview = f"在 '{target[:60]}' 之后插入"
    elif operation == "insert_before":
        new_body = before + content + "\n" + target_text + after
        preview = f"在 '{target[:60]}' 之前插入"
    elif operation == "replace":
        new_body = before + content + after
        preview = f"替换了 '{target[:60]}'"
    elif operation == "delete":
        new_body = before + after
        preview = f"删除了 '{target[:60]}'"
    else:
        return f"错误：未知操作 '{operation}'。"

    store.write(kind, slug, meta, new_body)

    return json.dumps({
        "ok": True,
        "operation": operation,
        "target_summary": preview,
        "preview": (content[:200] + "…") if len(content) > 200 else content,
    }, ensure_ascii=False)


@editor_tool(
    "search_docs",
    "跨文件搜索：按文本关键词和/或元数据条件查找文档。"
    "可用于查找「所有提到某个词的文件」或「所有 nature 为空的 NPC」等。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS) + ["all"],
                "description": "文档类型，或 'all' 搜索全部",
            },
            "query": {
                "type": "string",
                "description": "文本搜索词（可选，匹配 meta 和 body）",
            },
            "meta_filter": {
                "type": "object",
                "description": "元数据过滤条件，如 {level: '主要', status: '进行中'}。键值对 AND 逻辑。",
            },
            "limit": {
                "type": "integer",
                "description": "最大返回数（默认 20）",
            },
        },
        "required": ["kind"],
    },
)
async def search_docs(store: store_mod.Store, kind: str, query: str = "",
                      meta_filter: dict[str, Any] | None = None,
                      limit: int = 20) -> str:
    kinds = list(VALID_KINDS) if kind == "all" else [kind]
    meta_filter = meta_filter or {}
    query_lower = query.lower() if query else ""
    results: list[dict] = []

    for k in kinds:
        docs = store.list_docs(k)
        for d in docs:
            slug = d["slug"]
            meta = d["meta"]
            name = meta.get("name") or meta.get("title") or meta.get("term") or slug

            # 元数据过滤
            if meta_filter:
                match = True
                for mf_key, mf_val in meta_filter.items():
                    if str(meta.get(mf_key, "")).strip().lower() != str(mf_val).strip().lower():
                        match = False
                        break
                if not match:
                    continue

            # 文本搜索
            snippet = ""
            if query:
                score = 0
                # 匹配 meta
                meta_str = json.dumps(meta, ensure_ascii=False, default=str).lower()
                score += meta_str.count(query_lower) * 3
                # 匹配 slug
                if query_lower in slug.lower():
                    score += 5
                # 匹配 body
                try:
                    _, body = store.read(k, slug) or ({}, "")
                    body_score = body.lower().count(query_lower)
                    score += body_score
                    if body_score > 0:
                        # 提取片段
                        qidx = body.lower().find(query_lower)
                        start = max(0, qidx - 40)
                        end = min(len(body), qidx + len(query) + 60)
                        snippet = ("…" if start > 0 else "") + body[start:end].replace("\n", " ") + ("…" if end < len(body) else "")
                except Exception:
                    pass
                if score == 0:
                    continue

            entry = {
                "kind": k, "slug": slug, "name": name,
                "meta_summary": {k2: meta.get(k2) for k2 in ("level", "identity", "nature", "status", "type")
                                 if meta.get(k2)},
            }
            if snippet:
                entry["snippet"] = snippet
            results.append(entry)

    results = results[:limit]
    return json.dumps({
        "total": len(results),
        "results": results,
    }, ensure_ascii=False, default=str)


# ===========================================================================
# B 类：Front Matter 规范化工具
# ===========================================================================

@editor_tool(
    "validate_doc",
    "按类型 schema 校验单个文件的 front matter。检查必填字段、枚举值、类型、跨文件引用。"
    "read_doc 已自动附带校验结果——通常不需要单独调用此工具。用于批量检查或复查场景。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "slug": {"type": "string", "description": "文档 slug"},
        },
        "required": ["kind", "slug"],
    },
)
async def validate_doc(store: store_mod.Store, kind: str, slug: str) -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。"
    meta, _ = d
    vr = schema_validator.validate(meta, kind, store)

    return json.dumps({
        "kind": kind,
        "slug": slug,
        "valid": vr.valid,
        "errors_count": len(vr.errors),
        "warnings_count": len(vr.warnings),
        "info_count": len(vr.info),
        "summary": vr.summary,
        "errors": [{"field": e.field, "message": e.message} for e in vr.errors],
        "warnings": [{"field": w.field, "message": w.message} for w in vr.warnings],
        "info": [{"field": i.field, "message": i.message} for i in vr.info],
    }, ensure_ascii=False)


@editor_tool(
    "normalize_doc",
    "自动修复单个文件的 front matter 问题：补全默认值、修正枚举值格式、从正文提取信息。"
    "默认开启 clean_system_fields（清理 front matter 中的冗余 slug/updated）。"
    "dry_run=true 时仅预览不改动。",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(VALID_KINDS), "description": "文档类型"},
            "slug": {"type": "string", "description": "文档 slug"},
            "fill_defaults": {"type": "boolean", "description": "为缺失字段填入默认值（默认 true）"},
            "fix_enums": {"type": "boolean", "description": "修正非标准枚举值（默认 true）"},
            "extract_from_body": {"type": "boolean", "description": "从正文提取信息补全 meta（默认 true）"},
            "clean_system_fields": {"type": "boolean", "description": "清理 front matter 中的 slug/updated（默认 true）"},
            "dry_run": {"type": "boolean", "description": "仅预览不改动（默认 false）"},
        },
        "required": ["kind", "slug"],
    },
)
async def normalize_doc(store: store_mod.Store, kind: str, slug: str,
                        fill_defaults: bool = True,
                        fix_enums: bool = True,
                        extract_from_body: bool = True,
                        clean_system_fields: bool = True,
                        dry_run: bool = False) -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。"
    meta, body = d

    result = schema_normalizer.normalize(
        meta, body, kind,
        fill_defaults=fill_defaults,
        fix_enums=fix_enums,
        extract_from_body=extract_from_body,
        clean_system_fields=clean_system_fields,
    )

    if not result.changes:
        return f"{kind}/{slug} 无需修改，front matter 已符合规范。"

    if dry_run:
        return json.dumps({
            "dry_run": True,
            "changes_preview": [
                {"field": c.field, "old": c.old_value, "new": c.new_value, "source": c.source}
                for c in result.changes
            ],
        }, ensure_ascii=False, default=str)

    # 实际写入
    store.write(kind, slug, result.meta, body)

    # 写入后校验
    vr = schema_validator.validate(result.meta, kind, store)

    return json.dumps({
        "ok": True,
        "changes": [
            {"field": c.field, "old": c.old_value, "new": c.new_value, "source": c.source}
            for c in result.changes
        ],
        "remaining_issues": {
            "errors": len(vr.errors),
            "warnings": len(vr.warnings),
            "errors_detail": [{"field": e.field, "message": e.message} for e in vr.errors],
            "warnings_detail": [{"field": w.field, "message": w.message} for w in vr.warnings],
        },
    }, ensure_ascii=False, default=str)


@editor_tool(
    "validate_all",
    "批量校验整个游戏目录（或指定类型）的所有文件，生成校验报告。"
    "用于了解项目整体的 front matter 规范程度。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS) + ["all"],
                "description": "文档类型，或 'all' 校验全部（默认 all）",
            },
        },
        "required": [],
    },
)
async def validate_all(store: store_mod.Store, kind: str = "all") -> str:
    kinds = list(VALID_KINDS) if kind == "all" else [kind]
    total = 0
    valid_count = 0
    with_errors = 0
    with_warnings = 0
    by_kind: dict[str, dict] = {}
    details: list[dict] = []

    for k in kinds:
        docs = store.list_docs(k)
        k_total = len(docs)
        k_valid = 0
        k_errors = 0
        k_warnings = 0
        for d in docs:
            total += 1
            meta, _ = store.read(k, d["slug"]) or ({}, "")
            vr = schema_validator.validate(meta, k, store)
            if vr.valid:
                k_valid += 1
                valid_count += 1
            if vr.errors:
                k_errors += 1
                with_errors += 1
            if vr.warnings:
                k_warnings += 1
                with_warnings += 1
            if vr.errors or vr.warnings:
                details.append({
                    "kind": k, "slug": d["slug"],
                    "errors": [{"field": e.field, "message": e.message} for e in vr.errors],
                    "warnings": [{"field": w.field, "message": w.message} for w in vr.warnings],
                })
        by_kind[k] = {"total": k_total, "valid": k_valid, "with_errors": k_errors, "with_warnings": k_warnings}

    return json.dumps({
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "total_files": total,
            "valid": valid_count,
            "with_errors": with_errors,
            "with_warnings": with_warnings,
            "by_kind": by_kind,
        },
        "details": details[:30],  # 最多 30 条详情
        "details_truncated": len(details) > 30,
    }, ensure_ascii=False, default=str)


@editor_tool(
    "normalize_all",
    "批量自动修复所有文件（或指定类型）的 front matter。默认 dry_run=true（先预览）。"
    "请务必先 dry_run 预览变更，确认无误后再设 dry_run=false 执行。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS) + ["all"],
                "description": "文档类型，或 'all' 处理全部（默认 all）",
            },
            "fill_defaults": {"type": "boolean", "description": "填入默认值（默认 true）"},
            "fix_enums": {"type": "boolean", "description": "修正枚举值（默认 true）"},
            "extract_from_body": {"type": "boolean", "description": "从正文提取（默认 true）"},
            "clean_system_fields": {"type": "boolean", "description": "清理系统字段（默认 true）"},
            "dry_run": {"type": "boolean", "description": "仅预览不改动（默认 true，安全优先）"},
        },
        "required": [],
    },
)
async def normalize_all(store: store_mod.Store, kind: str = "all",
                        fill_defaults: bool = True,
                        fix_enums: bool = True,
                        extract_from_body: bool = True,
                        clean_system_fields: bool = True,
                        dry_run: bool = True) -> str:
    kinds = list(VALID_KINDS) if kind == "all" else [kind]
    all_changes: list[dict] = []
    total_files = 0
    changed_files = 0

    for k in kinds:
        docs = store.list_docs(k)
        for d in docs:
            total_files += 1
            meta, body = store.read(k, d["slug"]) or ({}, "")
            result = schema_normalizer.normalize(
                meta, body, k,
                fill_defaults=fill_defaults,
                fix_enums=fix_enums,
                extract_from_body=extract_from_body,
                clean_system_fields=clean_system_fields,
            )
            if result.changes:
                changed_files += 1
                for c in result.changes:
                    all_changes.append({
                        "kind": k, "slug": d["slug"],
                        "field": c.field,
                        "old": str(c.old_value)[:80],
                        "new": str(c.new_value)[:80],
                        "source": c.source,
                    })
                if not dry_run:
                    store.write(k, d["slug"], result.meta, body)

    if dry_run:
        return json.dumps({
            "dry_run": True,
            "summary": {
                "total_files": total_files,
                "would_change": changed_files,
                "would_fix": len(all_changes),
            },
            "preview": all_changes[:40],
            "preview_truncated": len(all_changes) > 40,
        }, ensure_ascii=False, default=str)
    else:
        return json.dumps({
            "dry_run": False,
            "summary": {
                "total_files": total_files,
                "changed": changed_files,
                "fixes_applied": len(all_changes),
            },
            "changes": all_changes[:40],
            "changes_truncated": len(all_changes) > 40,
        }, ensure_ascii=False, default=str)


# ===========================================================================
# C 类：辅助工具
# ===========================================================================

@editor_tool(
    "list_docs",
    "列出指定类型的所有文档，含关键字段摘要和问题计数。比 search_docs 更轻量，用于浏览。",
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(VALID_KINDS),
                "description": "文档类型",
            },
            "sort_by": {
                "type": "string",
                "enum": ["name", "updated", "slug"],
                "description": "排序方式（默认 name）",
            },
            "limit": {"type": "integer", "description": "最大返回数（默认 50）"},
            "offset": {"type": "integer", "description": "分页偏移（默认 0）"},
        },
        "required": ["kind"],
    },
)
async def list_docs(store: store_mod.Store, kind: str, sort_by: str = "name",
                    limit: int = 50, offset: int = 0) -> str:
    docs = store.list_docs(kind)
    items = []
    for d in docs:
        name = d["meta"].get("name") or d["meta"].get("title") or d["meta"].get("term") or d["slug"]
        highlights = {}
        for k2 in ("level", "identity", "nature", "status", "current_stage", "type", "category"):
            if d["meta"].get(k2):
                highlights[k2] = d["meta"][k2]
        updated = d["meta"].get("updated", "")
        items.append({
            "slug": d["slug"],
            "name": name,
            "meta_highlights": highlights,
            "updated": updated,
        })

    # 排序
    if sort_by == "name":
        items.sort(key=lambda x: x["name"])
    elif sort_by == "updated":
        items.sort(key=lambda x: x["updated"], reverse=True)
    # slug 排序是默认（list_docs 已按文件名排序）

    total = len(items)
    items = items[offset:offset + limit]

    return json.dumps({"total": total, "items": items}, ensure_ascii=False, default=str)


@editor_tool(
    "delete_doc",
    "删除一个文档文件。不可逆操作，请谨慎。",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(VALID_KINDS), "description": "文档类型"},
            "slug": {"type": "string", "description": "文档 slug"},
        },
        "required": ["kind", "slug"],
    },
)
async def delete_doc(store: store_mod.Store, kind: str, slug: str) -> str:
    d = store.read(kind, slug)
    if d is None:
        return f"错误：{kind}/{slug} 不存在。"
    name = d[0].get("name", slug)

    p = store._path(kind, slug)
    p.unlink(missing_ok=True)

    return json.dumps({
        "ok": True,
        "deleted": str(p),
        "name": name,
    }, ensure_ascii=False)


@editor_tool(
    "rename_doc",
    "重命名文档（改变 slug/文件名）。自动扫描其他文档中引用旧 slug 的地方并更新。",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(VALID_KINDS), "description": "文档类型"},
            "old_slug": {"type": "string", "description": "当前 slug"},
            "new_slug": {"type": "string", "description": "新 slug（不要带 .md 后缀）"},
        },
        "required": ["kind", "old_slug", "new_slug"],
    },
)
async def rename_doc(store: store_mod.Store, kind: str, old_slug: str, new_slug: str) -> str:
    d = store.read(kind, old_slug)
    if d is None:
        return f"错误：{kind}/{old_slug} 不存在。"
    meta, body = d

    old_path = store._path(kind, old_slug)
    new_path = store._path(kind, new_slug)

    if new_path.exists():
        return f"错误：目标 {kind}/{new_slug} 已存在。"

    # 扫描引用
    refs_updated = 0
    for k in VALID_KINDS:
        docs = store.list_docs(k)
        for doc in docs:
            if k == kind and doc["slug"] == old_slug:
                continue  # 跳过自身
            m, b = store.read(k, doc["slug"]) or ({}, "")
            if not b:
                continue
            if old_slug in b:
                b = b.replace(old_slug, new_slug)
                refs_updated += 1
                store.write(k, doc["slug"], m, b)

    # 执行重命名
    old_path.rename(new_path)

    return json.dumps({
        "ok": True,
        "old_slug": old_slug,
        "new_slug": new_slug,
        "old_path": str(old_path),
        "new_path": str(new_path),
        "references_updated": refs_updated,
    }, ensure_ascii=False)
