"""store.py --- TRPG 上下文目录加载与持久化。

吃一个符合 agent.md 规划的目录，提供统一的读写接口。

冷启动行为：
- 空目录/不存在的目录 → 自动创建完整目录骨架 + 占位文件
  （agent.md / world-book.md / style-guide.md，标注"尚未配置"）
- 已有文件但缺失关键文件 → 自动补全占位文件
- 目录结构可疑（有文件但不像游戏目录）→ 警告但不拒绝

线程/进程安全：Store 使用基于文件创建原子性的跨平台文件锁
（.atrpg/.lock），保护 write/append_body 等写操作。
多进程（如 NoneBot QQ + 独立 Web API 并行）可安全共享 data/ 目录。

对话历史：由 core/context.py + core/db.py 管理（tree_nodes + messages 表），
本模块不再处理 LLM 会话历史（load_history 委托给 context.build_context）。
"""

from __future__ import annotations

import os
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = ["Store", "StoreError", "slugify", "char_color"]


def slugify(text: str) -> str:
    """生成 slug：小写、中英数、连字符分隔。"""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "untitled"


def char_color(name: str) -> int:
    """基于角色名生成稳定的色相值（0-360）。相同名字始终得到相同色相。

    不同名字均匀扩散在色环上，视觉上天然分散。
    """
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xffff
    return h % 360


class StoreError(Exception):
    """目录不符合 agent.md 规划时的错误。"""


# YAML 前置 + Markdown 正文 的文档结构
_DOC_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

# ---------- 冷启动占位模板加载 ----------

_PLACEHOLDER_DIR = Path(__file__).resolve().parent.parent / "templates"

_PLACEHOLDER_MAP: dict[str, Path] = {
    "agent": _PLACEHOLDER_DIR / "placeholder-agent.md",
    "world-book": _PLACEHOLDER_DIR / "placeholder-world-book.md",
    "style-guide": _PLACEHOLDER_DIR / "placeholder-style-guide.md",
}


def _read_placeholder(kind: str) -> str:
    """从 templates/ 目录读取占位模板内容。"""
    path = _PLACEHOLDER_MAP.get(kind)
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    # 回退：模板文件缺失时的硬编码最小占位
    fallbacks = {
        "agent": "# ATRPG 游戏目录\n\n> ⚠️ 尚未配置。\n",
        "world-book": "---\nname: 世界书\ntype: 世界书\n---\n\n# 世界书\n\n> ⚠️ 尚未配置。\n",
        "style-guide": "---\nname: 文风参考\ntype: 文风参考\n---\n\n# 文风参考\n\n> ⚠️ 尚未配置。\n",
    }
    return fallbacks.get(kind, "")

# --- Front Matter 字段名国际化映射 ---
# 中文 → 英文。_parse_doc 读取时自动翻译，_dump_doc 写入时保持英文。
# 所有代码和 LLM 提示词统一使用英文字段名。
_FIELD_MAP: dict[str, str] = {
    # 通用
    "名称": "name",
    "姓名": "name",
    "标题": "title",
    "术语": "term",
    "类型": "type",
    "性质": "nature",
    "身份": "identity",
    "状态": "status",
    "级别": "level",
    "类别": "category",
    "简要定义": "brief",
    "一句话梗概": "hook",
    "日期": "date",
    "来源": "source",
    "所属": "parent",
    "基调": "tone",
    # 弧光专用
    "规划者": "planner",
    "当前阶段": "current_stage",
    "关联要素": "related",
    "影响范围": "scope",
    "跨度": "span",
    "弧光名称": "arc_title",
    # 情境 / 角色 专用
    "地点": "location",
    "在场者": "attendees",
    "当前地点": "current_location",
    "当前场景": "current_location",
    "当前情景": "current_location",
    # 道具
    "道具": "items",  # 弧光“关联要素”子键
}


def _translate_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """将 meta 中的中文键翻译为英文键，实现向后兼容。

    规则：
    1. 已是英文的键直接保留（不在 _FIELD_MAP 中的键一律视为英文/自定义键）。
    2. 中文键翻译为英文，但仅当对应英文键尚不存在时才填入。
    3. 这样「新英文键总是赢」，不会覆盖代码已写入的新值。
    """
    translated: dict[str, Any] = {}
    # 第一遍：保留所有已是英文的键
    for k, v in meta.items():
        if k not in _FIELD_MAP:
            translated[k] = v
    # 第二遍：翻译中文键，跳过已有英文值的键
    for k, v in meta.items():
        en_key = _FIELD_MAP.get(k)
        if en_key and en_key not in translated:
            translated[en_key] = v
    return translated


def _parse_doc(text: str) -> tuple[dict[str, Any], str]:
    """解析 YAML front matter + Markdown body。无 front matter 时返回 ({}, text)。

    自动将中文键翻译为英文键，实现向后兼容。
    """
    m = _DOC_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return _translate_meta(meta), m.group(2)


def _dump_doc(meta: dict[str, Any], body: str) -> str:
    """把 meta + body 序列化为 front matter 文档。始终输出英文字段名。"""
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}"


@dataclass
class Session:
    """团会话状态：群号 ↔ 团、角色→情景映射、进行中弧光。"""

    group_id: str
    game_name: str = ""
    status: str = "进行中"  # 进行中 / 暂停 / 已归档
    char_scene_map: dict[str, str] = field(default_factory=dict)  # 角色 slug → 情景 slug
    active_arcs: list[dict[str, str]] = field(default_factory=list)
    pending_director: bool = False
    last_active: str = ""

    def to_meta(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "game_name": self.game_name,
            "status": self.status,
            "char_scene_map": self.char_scene_map,
            "active_arcs": self.active_arcs,
            "pending_director": self.pending_director,
            "last_active": self.last_active,
        }


class _FileLock:
    """跨平台文件锁，基于文件创建原子性（O_CREAT | O_EXCL）。

    用于保护 store 的写操作，使多进程（QQ + Web API 并行）安全共享 data/ 目录。
    不依赖 msvcrt/fcntl，纯 Python 标准库实现。

    超时后抛出 TimeoutError，由调用方决定是否重试或报错。
    """

    def __init__(self, lock_path: str | Path, timeout: float = 10.0, poll_interval: float = 0.05):
        self.lock_path = str(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: int | None = None

    def acquire(self) -> None:
        start = time.monotonic()
        while True:
            try:
                self._fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                # 写入当前 PID，便于调试死锁
                os.write(self._fd, str(os.getpid()).encode())
                return
            except FileExistsError:
                if time.monotonic() - start > self.timeout:
                    # 尝试读取锁文件中的 PID
                    pid_info = ""
                    try:
                        pid_info = f" (持有者 PID 可能为：{Path(self.lock_path).read_text().strip()})"
                    except OSError:
                        pass
                    raise TimeoutError(
                        f"无法获取文件锁（超时 {self.timeout}s）{pid_info}"
                    )
                time.sleep(self.poll_interval)

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
            try:
                os.remove(self.lock_path)
            except OSError:
                pass

    def __enter__(self) -> _FileLock:
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class Store:
    """TRPG 上下文目录的读写门面。"""

    SUBDIRS = (
        "characters",
        "npcs",
        "locations",
        "scenes",
        "items",
        "story-arcs",
        "state-records",
        "terminology",
        "sessions",
    )

    def __init__(self, game_dir: str | Path):
        self.root = Path(game_dir).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True)
            logger.info(f"创建游戏目录: {self.root}")
        elif not self.root.is_dir():
            raise StoreError(f"路径存在但不是目录: {self.root}")
        self._ensure_subdirs()
        self._init_databases()
        self._validate()

    # ---------- 目录校验 ----------
    def _ensure_subdirs(self) -> None:
        (self.root / "data").mkdir(exist_ok=True)
        for sub in self.SUBDIRS:
            (self.root / "data" / sub).mkdir(exist_ok=True)
        # .atrpg/ 放运行时缓存（LLM 对话历史等），不是数据源
        (self.root / ".atrpg" / "history").mkdir(parents=True, exist_ok=True)
        # 备团编辑器上传的文件（PDF/DOC 等参考材料）
        (self.root / ".atrpg" / "uploads").mkdir(parents=True, exist_ok=True)

    def _init_databases(self) -> None:
        """初始化 SQLite 数据库（聊天室 + 会话树）。"""
        from . import db as _db
        try:
            _db.init_chat(self.root)
            _db.init_session(self.root)
        except Exception:
            logger.warning("数据库初始化失败（可能已存在）", exc_info=True)

    def _validate(self) -> None:
        """启动校验 + 冷启动自动初始化。

        三级策略：
        1. 空目录（无 agent.md + 无任何世界材料）→ 创建全部占位文件
        2. 已有部分文件 → 检查完整性，自动补全缺失的占位文件
        3. 目录结构可疑 → 警告（但不拒绝，允许用户自行修复）

        弧光/情景/地点都不强制——没有预置主要弧光也能开团。
        """
        has_agent = (self.root / "agent.md").exists()
        has_wb = (self.root / "data" / "world-book.md").exists()
        has_raw = bool(self.list_world_material())
        has_style = (self.root / "data" / "style-guide.md").exists()

        # --- 场景 1：空目录（无 agent 且无任何材料）---
        is_empty = not has_agent and not has_wb and not has_raw
        if is_empty:
            self._create_placeholders(all=True)
            logger.info("空目录：已创建占位文件（agent.md / world-book.md / style-guide.md）")
            return

        # --- 场景 2：已有部分文件，检查完整性并自动补全 ---
        if not has_wb and not has_raw:
            self._create_placeholder("world-book")
            logger.info("缺少世界材料，已创建占位 world-book.md")
        if not has_style:
            self._create_placeholder("style-guide")
            logger.info("缺少文风参考，已创建占位 style-guide.md")
        if not has_agent:
            self._create_placeholder("agent")
            logger.info("缺少 agent.md，已创建占位")

        # --- 场景 3：可疑目录检测（有文件但完全不符合预期结构）---
        self._check_suspicious(has_agent, has_wb, has_raw)

    def _check_suspicious(
        self, has_agent: bool, has_wb: bool, has_raw: bool
    ) -> None:
        """检测目录是否可能是一个非 ATRPG 游戏目录。

        触发条件：有任意文件/子目录，但不含 agent.md、world-book.md、
        原始材料，且 data/ 下没有任何预期的子目录。
        """
        data_dir = self.root / "data"
        has_expected_subdirs = data_dir.is_dir() and any(
            (data_dir / sub).is_dir() for sub in self.SUBDIRS
        )
        # 根目录是否有其他文件（排除 agent.md 和占位文件）
        root_files = [
            p for p in self.root.iterdir()
            if p.name not in ("agent.md", "data", ".atrpg", ".git")
        ]
        has_other_files = bool(root_files)

        if not has_agent and not has_wb and not has_raw and not has_expected_subdirs:
            if has_other_files:
                logger.warning(
                    "⚠️ 目录结构不符合预期：根目录有文件但缺少 agent.md、data/ 子目录和世界材料。"
                    "如果这不是一个 ATRPG 游戏目录，请检查 --game-dir 配置是否正确。"
                    "根目录现有文件: %s",
                    [p.name for p in root_files],
                )

    def _create_placeholders(self, *, all: bool = False) -> None:
        """批量创建占位文件。"""
        if all:
            self._create_placeholder("agent")
            self._create_placeholder("world-book")
            self._create_placeholder("style-guide")
        else:
            # 仅创建缺失的
            if not (self.root / "agent.md").exists():
                self._create_placeholder("agent")
            if not (self.root / "data" / "world-book.md").exists():
                self._create_placeholder("world-book")
            if not (self.root / "data" / "style-guide.md").exists():
                self._create_placeholder("style-guide")

    def _create_placeholder(self, kind: str) -> None:
        """创建单个占位文件（内容从 templates/ 目录读取）。"""
        targets = {
            "agent": self.root / "agent.md",
            "world-book": self.root / "data" / "world-book.md",
            "style-guide": self.root / "data" / "style-guide.md",
        }
        path = targets[kind]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_read_placeholder(kind), encoding="utf-8")
        logger.debug(f"创建占位文件: {path.relative_to(self.root)}")

    # ---------- 通用读写 ----------
    def _path(self, kind: str, slug: str) -> Path:
        """构造 data/{kind}/{slug}.md 路径，并校验防路径穿越。"""
        if not kind or not slug:
            raise StoreError("kind/slug 不能为空")
        if any(ord(ch) < 32 or ch in ("/", "\\") for ch in slug):
            raise StoreError(f"slug 含非法字符: {slug!r}")
        if slug in (".", ".."):
            raise StoreError(f"slug 非法: {slug!r}")
        p = self.root / "data" / kind / f"{slug}.md"
        base = (self.root / "data" / kind).resolve()
        if not p.resolve().is_relative_to(base):
            raise StoreError(f"路径越界: {kind}/{slug}")
        return p

    def read(self, kind: str, slug: str) -> tuple[dict[str, Any], str] | None:
        """读取一篇文档，返回 (meta, body)。不存在返回 None。"""
        p = self._path(kind, slug)
        if not p.exists():
            return None
        return _parse_doc(p.read_text(encoding="utf-8"))

    def write(self, kind: str, slug: str, meta: dict[str, Any], body: str) -> Path:
        """写入文档（覆盖）。自动补生成时间戳。"""
        meta = {**meta}
        meta.setdefault("updated", datetime.now().strftime("%Y-%m-%d %H:%M"))
        p = self._path(kind, slug)
        content = _dump_doc(meta, body)
        with _FileLock(self.root / ".atrpg" / ".lock"):
            p.write_text(content, encoding="utf-8")
        logger.debug(f"store write: {kind}/{slug} body={len(body)}chars")
        return p

    def append_body(self, kind: str, slug: str, chunk: str) -> None:
        """向文档正文末尾追加内容（保留 front matter meta）。文件不存在则创建。"""
        p = self._path(kind, slug)
        if p.exists():
            with _FileLock(self.root / ".atrpg" / ".lock"):
                meta, body = _parse_doc(p.read_text(encoding="utf-8"))
                body = body.rstrip() + "\n\n" + chunk + "\n"
                meta = {**meta}
                meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                p.write_text(_dump_doc(meta, body), encoding="utf-8")
        else:
            self.write(kind, slug, {}, chunk)

    def list_docs(self, kind: str) -> list[dict[str, Any]]:
        """列出某类下的所有文档摘要 {slug, meta}。"""
        out = []
        for p in sorted((self.root / "data" / kind).glob("*.md")):
            meta, _ = _parse_doc(p.read_text(encoding="utf-8"))
            out.append({"slug": p.stem, "meta": meta})
        return out

    # ---------- 便捷业务接口 ----------
    def list_world_material(self) -> list[Path]:
        """列出根目录下的世界基础材料文件（.txt/.md，规则书/世界设定）。

        排除 agent.md / project.md / README 这类项目说明文件。
        这些文件是 LLM 主持人的世界知识来源。
        """
        excluded = {"agent.md", "project.md", "readme.md", "license"}
        out = []
        for p in sorted(self.root.glob("*.txt")):
            out.append(p)
        for p in sorted(self.root.glob("*.md")):
            if p.name.lower() not in excluded:
                out.append(p)
        return out

    def read_world_material(self, max_chars: int = 12000) -> str:
        """读取并拼接世界基础材料，喂给 LLM 作世界观上下文。

        多个文件按文件名排序，预算均匀分配给每个文件（避免第一个大文件吃光额度）。
        每个文件截取前 (max_chars // 文件数) 字符，整体不超过 max_chars。
        """
        files = self.list_world_material()
        if not files:
            return ""
        per_file = max_chars // len(files)
        parts: list[str] = []
        for p in files:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(text) > per_file:
                parts.append(f"=== {p.name}（截断，仅前 {per_file} 字）===\n{text[:per_file]}")
            else:
                parts.append(f"=== {p.name} ===\n{text}")
        return "\n\n".join(parts)

    def read_world_book(self) -> str:
        """读取世界书作为 LLM 主持人的常驻世界观知识。

        优先读 data/world-book.md（经 build_world_book.py 总结，精炼推荐）；
        不存在则回退 read_world_material()（原始 pdf_extract，兼容未预处理目录）。
        """
        wb = self.root / "data" / "world-book.md"
        if wb.exists():
            _, body = _parse_doc(wb.read_text(encoding="utf-8"))
            return body
        return self.read_world_material()

    def read_style_guide(self) -> str:
        """读取文风参考（data/style-guide.md）。不存在返回空串。"""
        sg = self.root / "data" / "style-guide.md"
        if sg.exists():
            _, body = _parse_doc(sg.read_text(encoding="utf-8"))
            return body
        return ""

    # ---------- 运行时缓存（.atrpg/，纯 LLM 对话历史，非数据源）----------
    def load_history(self, session_key: str) -> list[dict[str, Any]]:
        """加载对话历史：从树 + messages 表重建（消息粒度化存储）。

        session_key 参数保留用于兼容，实际以活跃分支为准。
        返回不含 system prefix 的对话消息列表。
        """
        from .config import get_context_config
        from .context import build_context
        from .db import session_get_active_branch

        cfg = get_context_config()
        branch_id = session_get_active_branch(self.root)
        msgs = build_context(
            self.root,
            branch_id=branch_id,
            system_prefix="",
            window_keep=cfg.get("window_keep", 20),
            window_slide=cfg.get("window_slide", 5),
        )
        logger.info(f"load_history: {len(msgs)}条 (branch={branch_id})")
        return msgs

    # ---------- 位置追踪 ----------
    def char_current_scene(self, char_slug: str) -> str | None:
        """读角色文件的 current_location 字段（首要来源）。"""
        d = self.read("characters", char_slug)
        if d is None:
            return None
        return d[0].get("current_location")

    def npc_current_scene(self, npc_slug: str) -> str | None:
        """读 NPC 文件的 current_location 字段。"""
        d = self.read("npcs", npc_slug)
        if d is None:
            return None
        return d[0].get("current_location")

    def set_char_current_scene(self, char_slug: str, scene_slug: str) -> None:
        """写角色文件的 current_location 字段。"""
        d = self.read("characters", char_slug)
        if d is None:
            raise StoreError(f"角色 {char_slug} 不存在")
        meta, body = d
        meta["current_location"] = scene_slug
        self.write("characters", char_slug, meta, body)

    def set_npc_current_scene(self, npc_slug: str, scene_slug: str) -> None:
        """写 NPC 文件的 current_location 字段。"""
        d = self.read("npcs", npc_slug)
        if d is None:
            raise StoreError(f"NPC {npc_slug} 不存在")
        meta, body = d
        meta["current_location"] = scene_slug
        self.write("npcs", npc_slug, meta, body)

    def who_in_scene(self, scene_slug: str) -> tuple[list[str], list[str]]:
        """扫描所有角色和 NPC 文件，返回 (角色slug列表, NPC slug列表)。"""
        chars, npcs = [], []
        for d in self.list_docs("characters"):
            if d["meta"].get("current_location") == scene_slug:
                chars.append(d["slug"])
        for d in self.list_docs("npcs"):
            if d["meta"].get("current_location") == scene_slug:
                npcs.append(d["slug"])
        return chars, npcs

    def scene_location(self, scene_slug: str) -> str | None:
        """读情景文件的 location 字段。"""
        d = self.read("scenes", scene_slug)
        if d is None:
            return None
        return d[0].get("location")

    def location_name(self, loc_slug: str) -> str | None:
        """读地点文件的 name 字段。"""
        d = self.read("locations", loc_slug)
        if d is None:
            return None
        return d[0].get("name")

    def all_char_locations(self, group_id: str) -> dict[str, str]:
        """扫描所有角色和 NPC 文件，返回 slug → 情景 slug。"""
        result: dict[str, str] = {}
        for d in self.list_docs("characters"):
            cs = d["meta"].get("current_location")
            if cs:
                result[d["slug"]] = cs
        for d in self.list_docs("npcs"):
            cs = d["meta"].get("current_location")
            if cs:
                result[d["slug"]] = cs
        return result

    # 兼容旧接口：char_scene 尝试读角色文件，回退到 session map
    def char_scene(self, group_id: str, char_slug: str) -> str | None:
        cs = self.char_current_scene(char_slug)
        if cs:
            return cs
        # 回退：旧的 session map（逐步废弃）
        s = self.get_session(group_id)
        return s.char_scene_map.get(char_slug)

    def set_char_scene(self, group_id: str, char_slug: str, scene_slug: str) -> None:
        """写角色文件的 current_location（同时同步 session map 以保持兼容）。"""
        self.set_char_current_scene(char_slug, scene_slug)
        s = self.get_session(group_id)
        s.char_scene_map[char_slug] = scene_slug
        self.save_session(s)

    def player_binding(self, user_id: str) -> str | None:
        """QQ → 角色 slug（统一读 .atrpg/users/qq/）。"""
        from pathlib import Path as _P
        p = self.root / ".atrpg" / "users" / "qq" / f"{user_id}.json"
        if p.exists():
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                slug = data.get("character_slug")
                return slug if slug else None
            except Exception:
                pass
        return None

    def bind_player(self, user_id: str, char_slug: str, display_name: str = "") -> None:
        """绑定 QQ → 角色（统一写 .atrpg/users/qq/）。"""
        from pathlib import Path as _P
        p = self.root / ".atrpg" / "users" / "qq" / f"{user_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        import json, datetime as _dt
        data = {
            "provider": "qq",
            "id": str(user_id),
            "display_name": display_name or f"QQ_{str(user_id)[:8]}",
            "character_slug": char_slug if char_slug != "none" else None,
            "permission": "玩家",
            "joined": _dt.datetime.now().strftime("%Y-%m-%d"),
        }
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_session(self, group_id: str) -> Session:
        d = self.read("sessions", str(group_id))
        if d is None:
            return Session(group_id=str(group_id))
        m = d[0]
        return Session(
            group_id=m.get("group_id", str(group_id)),
            game_name=m.get("game_name", ""),
            status=m.get("status", "进行中"),
            char_scene_map=m.get("char_scene_map", {}),
            active_arcs=m.get("active_arcs", []),
            pending_director=m.get("pending_director", False),
            last_active=m.get("last_active", ""),
        )

    def save_session(self, s: Session) -> None:
        s.last_active = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.write("sessions", s.group_id, s.to_meta(), "")

