---
name: editor-doc-analysis
description: >-
  上传参考文档（PDF/DOC）的分析能力，用于 ATRPG 编辑助手。当编辑器中用户上传了设定集/
  小说片段/剧本等参考材料，需要理解文档、检索内容、按文档生成素材或产出分析报告时使用。
  核心价值：通过渐进式披露（索引常驻 / 按需读取 / 独立消化）保证文档全文不占用主对话上下文。
version: 1.0.0
---

# 上传文档分析（Editor Doc Analysis）

## Overview

编辑助手场景下，用户会上传 PDF/DOC 参考材料（设定集、小说片段、世界观资料等），解析为
`.atrpg/uploads/*.txt`。本技能定义如何让 AI 助手**使用**这些文档，而**不把全文塞进主对话**。

参照 Claude Skills 的渐进式披露（Progressive Disclosure）三级模型：

| 级别 | 机制 | 占用上下文 |
|------|------|-----------|
| L1 索引 | 上传时构建 `index.json`，system prompt 只注入「文件名/字符数/章节/预览」 | ~1KB/文件，常驻 |
| L2 按需读取 | `read_upload`（片段）/ `search_upload`（检索）工具，用时才读 | 仅当轮 tool result |
| L3 独立消化 | `analyze_upload` 触发独立 LLM 会话消化全文，报告落盘 `.analysis.md` | 主对话只见摘要 |

## When to use

- 用户上传参考文档后，**不要**自动请求全文、也不要把全文贴进对话。
- 用户问「文档里关于 X 的内容」→ `search_upload` 定位，`read_upload` 精读片段。
- 用户说「根据这份设定集生成角色卡/地点/物品」→ `analyze_upload` 整体消化，再按报告逐条 `write_doc`。
- 需要复核某段原文细节 → `read_upload`（按 offset 或 section）。

## Prerequisites

- 上传流程：`POST /api/editor/upload`（自动解析 + 自动 `build_index`）。
- 索引文件：`.atrpg/uploads/index.json`，缺省时读取侧自动重建。
- 核心逻辑：`core/doc_analysis.py`（无 LLM 依赖）。
- 独立消化提示词：`core/doc_analysis_runtime.md`。

## Instructions（给编辑助手 LLM）

1. system prompt 中只有「已上传参考文件（索引）」摘要：文件名、字符数、章节列表、首段预览。
2. 需要细节时按需调用，**禁止整篇读取**：
   - `read_upload(filename, offset|section, length)` — 单次读取默认 4000 字符、上限 8000。
   - `search_upload(query, filename?, limit?)` — 关键词检索，返回片段与位置。
3. 需要整体理解（生成素材、总结文档）时：
   - `analyze_upload(filename, task?)` — 独立会话消化全文，报告落盘 `.analysis.md`；
     返回 `report_path` 与 `report_head`，可直接 read_upload 读报告。
4. 读完片段或报告后，素材落盘走常规编辑工具（`write_doc` / `patch_meta` / `patch_body`），
   不要把大段原文粘贴到对话回复里。
5. 超长文档（>6 万字符）无法一次消化：先 `search_upload` 定位主题，再 `read_upload` 分段精读。

## Output Format

- 工具返回均为 JSON 字符串：`{"ok": true, ...}` 或 `{"ok": false, "error": ...}`。
- `read_upload` 返回 `offset/end/total_chars`，续读时传 `offset=end`。
- `analyze_upload` 报告为 Markdown，按 `doc-analysis-runtime` 的分节要求（概览/要点/可复用素材/一致性/摘要）。

## Error Handling

- 文件名找不到 → 用 `search_upload`（空 filename）确认确切的 txt 名。
- 章节关键词未命中 → `read_upload` 返回 `available_headings` 列表，换用精确标题。
- 路径穿越防护：所有文件访问都经过 `resolve()` 校验，只允许 `.atrpg/uploads/` 内。

## Resources

- 核心实现：`core/doc_analysis.py`（索引构建/加载、`index_summary`、`read_section`、`search`、`load_full_text`）
- 编辑器工具注册：`core/editor_tools.py` D 类（`read_upload` / `search_upload` / `analyze_upload`）
- 路由接入：`server/routes/editor.py`（chat 注入索引、upload/delete 刷新索引）
- CLI 维护脚本：`scripts/build_index.py`（重建索引）、`scripts/query.py`（检索/读片段）
- 参考实现范式：Claude Agent Skills（SKILL.md + scripts/ + references/ 分离，
  按需加载 references、assets 仅路径引用不加载进上下文）
