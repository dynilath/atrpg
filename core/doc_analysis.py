"""doc_analysis.py --- 上传文档的索引与按需读取（渐进式披露）。

设计目标：上传文档（PDF/DOC → 解析为 .txt）的**全文不应常驻 LLM 对话上下文**。
参照 Claude Skills 的渐进式披露（Progressive Disclosure）模式，分三级：

- L1 索引（常驻，轻量）：上传时构建 index.json，只把「文件名/字符数/章节/预览」
  注入 system prompt（每个文件约 1KB），而不是整篇全文。
- L2 按需读取（对话内，临时）：LLM 通过 read_upload / search_upload 工具
  在需要细节时才读取片段；片段只进入当轮 tool result，不常驻。
- L3 独立消化（离主对话）：长文档通过 analyze_upload 触发一次独立的 LLM
  调用消化全文，报告落盘 .atrpg/uploads/<txt>.analysis.md，主对话只见摘要。

本模块无 LLM 依赖，纯文件逻辑；CLI 薄壳见 skills/editor-doc-analysis/scripts/。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INDEX_FILE = "index.json"
MAX_PREVIEW_CHARS = 160          # 每个文件注入预览的长度
MAX_HEADINGS = 12                # 每个文件索引收录的章节数
MAX_INDEX_FILES = 20             # index_summary 最多展示的文件数
READ_SECTION_DEFAULT = 4000      # read_upload 默认读取长度
READ_SECTION_MAX = 8000          # read_upload 单次读取上限
SEARCH_SNIPPET = 90              # search 片段上下文长度

# 章节行识别：markdown 标题 / 中文章节 / 数字小节
_HEADING_PATTERNS = [
    re.compile(r"^#{1,4}\s+\S.*$"),
    re.compile(r"^第[一二三四五六七八九十百千万0-9]+[章节部篇卷].*$"),
    re.compile(r"^[0-9]+[.、．]\s*\S.*$"),
]


# ===========================================================================
# 索引构建 / 加载
# ===========================================================================

def _extract_headings(text: str, limit: int = MAX_HEADINGS) -> list[str]:
    """从解析文本中提取章节标题（尽力而为，PDF 转文本常无 markdown 标题）。"""
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 60:
            continue
        if any(p.match(stripped) for p in _HEADING_PATTERNS):
            # 折叠多余空白
            norm = re.sub(r"\s+", " ", stripped)
            if norm not in found:
                found.append(norm)
        if len(found) >= limit:
            break
    return found


def _preview(text: str, limit: int = MAX_PREVIEW_CHARS) -> str:
    """生成首段预览（折叠空白，截断加省略号）。"""
    head = re.sub(r"\s+", " ", text).strip()
    if len(head) <= limit:
        return head
    return head[:limit] + "…"


def build_index(upload_dir: Path) -> dict[str, Any]:
    """扫描 uploads/*.txt，生成并落盘 index.json。返回索引字典。

    幂等：可随时重跑刷新（上传/删除后调用）。
    """
    upload_dir = Path(upload_dir)
    files: list[dict[str, Any]] = []

    if upload_dir.exists():
        for p in sorted(upload_dir.glob("*.txt"), reverse=True):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                logger.warning(f"doc_analysis: 读取失败 {p.name}")
                continue
            original = _find_original(upload_dir, p)
            files.append({
                "txt": p.name,
                "original": original or p.stem,
                "size": p.stat().st_size,
                "chars": len(text),
                "headings": _extract_headings(text),
                "preview": _preview(text),
            })

    index = {"built_at": _now(), "files": files}
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / INDEX_FILE).write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning(f"doc_analysis: 写索引失败 {e}")
    return index


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def load_index(upload_dir: Path) -> dict[str, Any]:
    """读取 index.json；不存在则现场构建。"""
    p = Path(upload_dir) / INDEX_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return build_index(upload_dir)


def _find_original(upload_dir: Path, txt_path: Path) -> str | None:
    """由 txt 反查原始上传文件（.pdf/.docx/.doc）。"""
    for ext in (".pdf", ".docx", ".doc"):
        candidate = txt_path.with_suffix(ext)
        if candidate.exists():
            return candidate.name
    return None


def _resolve_txt(upload_dir: Path, filename: str) -> Path | None:
    """定位 txt 文件：接受 txt 名或原始文件名（自动补 .txt）。防路径穿越。"""
    upload_dir = Path(upload_dir).resolve()
    raw = filename.strip()
    if not raw:
        return None

    # 显式给了 .txt
    if raw.lower().endswith(".txt"):
        cand = (upload_dir / raw).resolve()
        return cand if _inside(upload_dir, cand) and cand.exists() else None

    # 原始文件名（.pdf/.docx/.doc）→ 匹配同名 txt
    stem = Path(raw).stem
    cand = (upload_dir / f"{stem}.txt").resolve()
    if _inside(upload_dir, cand) and cand.exists():
        return cand

    # 前缀模糊匹配（时间戳前缀太长难记）
    for p in upload_dir.glob("*.txt"):
        if p.stem.endswith(stem):
            return p.resolve()
    return None


def _inside(upload_dir: Path, p: Path) -> bool:
    return str(p).startswith(str(upload_dir) + "\\") or str(p).startswith(str(upload_dir) + "/")


def load_full_text(upload_dir: Path, filename: str, max_chars: int = 60000):
    """读取上传文档全文（供 L3 独立消化）。

    Returns:
        (txt_path, text, truncated)
        - txt_path: Path | None（未找到时为 None）
        - text: 全文（超长截断）
        - truncated: 是否被截断
    """
    txt = _resolve_txt(upload_dir, filename)
    if txt is None:
        return None, "", False
    try:
        text = txt.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"doc_analysis: 全文读取失败 {txt.name}: {e}")
        return txt, "", False

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + f"\n\n[... 已截断（原 {len(text):,} 字符），如需全文请用 read_upload 分段读取 ...]"
    return txt, text, truncated


# ===========================================================================
# L1：轻量索引摘要（注入 system prompt）
# ===========================================================================

def index_summary(upload_dir: Path, max_files: int = MAX_INDEX_FILES) -> str:
    """生成上传文档的轻量索引文本，替代全文注入。

    返回格式（无上传文件时返回空串）：
    ## 已上传参考文件（索引）
    共 N 个文件。不要一次性读取全文：需要细节时用 read_upload / search_upload；
    长文档整体理解用 analyze_upload（独立消化，结果落盘）。
    ...
    """
    index = load_index(upload_dir)
    files = index.get("files", [])
    if not files:
        return ""

    lines = [
        "## 已上传参考文件（索引）",
        f"共 {len(files)} 个文件。**不要一次性读取全文**：需要细节时用 "
        "`read_upload`（按需读片段）或 `search_upload`（关键词检索）；"
        "长文档整体理解用 `analyze_upload`（独立消化，报告落盘）。",
    ]
    for f in files[:max_files]:
        headings = f.get("headings", [])
        h_str = " / ".join(headings[:8])
        lines.append(
            f"\n### {f.get('original', f['txt'])}"
            f"（{f.get('chars', 0):,} 字符 · {len(headings)} 章节）"
        )
        lines.append(f"- txt: `{f['txt']}`")
        if h_str:
            lines.append(f"- 章节: {h_str}" + ("…" if len(headings) > 8 else ""))
        lines.append(f"- 预览: {f.get('preview', '')}")
    if len(files) > max_files:
        lines.append(f"\n… 还有 {len(files) - max_files} 个文件，见 .atrpg/uploads/")

    return "\n".join(lines)


# ===========================================================================
# L2：按需读取 / 检索（供 editor tools 调用）
# ===========================================================================

def read_section(upload_dir: Path, filename: str, offset: int = 0,
                 length: int = READ_SECTION_DEFAULT, section: str = "") -> str:
    """按需读取上传文档片段。

    - 提供 section：定位第一个包含该关键词的行起点开始读。
    - 否则从 offset 起读 length 个字符（默认 4000，上限 8000）。
    返回 JSON 字符串（含位置信息，便于连续续读）。
    """
    txt = _resolve_txt(upload_dir, filename)
    if txt is None:
        return json.dumps({"ok": False, "error": f"未找到上传文件 '{filename}'。"
                                               "可用 search_upload 或查看索引确认 txt 名。"},
                          ensure_ascii=False)

    try:
        text = txt.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return json.dumps({"ok": False, "error": f"读取失败: {e}"}, ensure_ascii=False)

    total = len(text)
    if section:
        idx = text.find(section)
        if idx == -1:
            return json.dumps({"ok": False, "error": f"未在文档中找到章节关键词 '{section}'。",
                               "available_headings": _extract_headings(text, 20)},
                              ensure_ascii=False)
        start = idx
    else:
        start = max(0, min(int(offset), total))

    length = max(200, min(int(length), READ_SECTION_MAX))
    end = min(total, start + length)
    chunk = text[start:end]

    return json.dumps({
        "ok": True,
        "txt": txt.name,
        "section": section or None,
        "offset": start,
        "end": end,
        "length": len(chunk),
        "total_chars": total,
        "text": chunk,
        "hint": "如需继续，用 read_upload 传 offset=end 的值继续读取。"
                "读完全文后请用 write_doc/patch_meta 落盘素材，不要整篇粘贴到对话。",
    }, ensure_ascii=False)


def search(upload_dir: Path, query: str, filename: str = "", limit: int = 5) -> str:
    """在上传文档中关键词检索，返回匹配片段（标注位置便于后续精读）。

    - filename 为空时搜索全部 txt。
    返回 JSON 字符串。
    """
    query = query.strip()
    if not query:
        return json.dumps({"ok": False, "error": "query 不能为空"}, ensure_ascii=False)

    upload_dir = Path(upload_dir)
    if filename:
        targets = [t for t in (_resolve_txt(upload_dir, filename),) if t]
    else:
        targets = sorted(upload_dir.glob("*.txt"), reverse=True)

    q_low = query.lower()
    results: list[dict[str, Any]] = []
    for txt in targets:
        try:
            text = txt.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        low = text.lower()
        pos = 0
        while len(results) < limit:
            idx = low.find(q_low, pos)
            if idx == -1:
                break
            s = max(0, idx - SEARCH_SNIPPET)
            e = min(len(text), idx + len(query) + SEARCH_SNIPPET)
            snippet = ("…" if s > 0 else "") + text[s:e].replace("\n", " ") + ("…" if e < len(text) else "")
            results.append({
                "txt": txt.name,
                "offset": idx,
                "snippet": snippet,
            })
            pos = idx + len(query)
        if len(results) >= limit:
            break

    return json.dumps({
        "ok": True,
        "query": query,
        "total": len(results),
        "truncated": len(results) >= limit,
        "results": results,
        "hint": "对命中片段感兴趣时，用 read_upload 传 filename + offset 精读上下文。",
    }, ensure_ascii=False)
