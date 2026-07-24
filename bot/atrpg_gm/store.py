"""store.py — TRPG 上下文目录加载与持久化。

吃一个符合 agent.md 规划的目录，提供统一的读写接口。
启动时校验：至少 1 条主要弧光 + 若干场景/地点，否则拒绝开团。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Store", "StoreError", "slugify"]


def slugify(text: str) -> str:
    """生成 slug：小写、中英数、连字符分隔。"""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "untitled"


class StoreError(Exception):
    """目录不符合 agent.md 规划时的错误。"""


# YAML 前置 + Markdown 正文 的文档结构
_DOC_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_doc(text: str) -> tuple[dict[str, Any], str]:
    """解析 YAML front matter + Markdown body。无 front matter 时返回 ({}, text)。"""
    m = _DOC_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return meta, m.group(2)


def _dump_doc(meta: dict[str, Any], body: str) -> str:
    """把 meta + body 序列化为 front matter 文档。"""
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}"


@dataclass
class Session:
    """团会话状态：群号 ↔ 团、角色→场景映射、进行中弧光。"""

    group_id: str
    game_name: str = ""
    status: str = "进行中"  # 进行中 / 暂停 / 已归档
    char_scene_map: dict[str, str] = field(default_factory=dict)  # 角色 slug → 场景 slug
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
        "sessions",
        "players",
    )

    def __init__(self, game_dir: str | Path):
        self.root = Path(game_dir).resolve()
        if not self.root.is_dir():
            raise StoreError(f"游戏目录不存在: {self.root}")
        self._ensure_subdirs()
        self._validate()

    # ---------- 目录校验 ----------
    def _ensure_subdirs(self) -> None:
        (self.root / "data").mkdir(exist_ok=True)
        for sub in self.SUBDIRS:
            (self.root / "data" / sub).mkdir(exist_ok=True)

    def _validate(self) -> None:
        """启动校验：至少 1 条主要弧光 + 至少 1 个场景 + 至少 1 个地点。"""
        arcs = self.list_docs("story-arcs")
        major = [a for a in arcs if a["meta"].get("级别") == "主要"]
        if not major:
            raise StoreError(
                "目录缺少「主要」弧光（data/story-arcs/ 中无 级别: 主要 的文件）。"
                "请先由备团用户预置主要故事弧光。"
            )
        if not self.list_docs("scenes"):
            raise StoreError("目录缺少场景（data/scenes/ 为空）。")
        if not self.list_docs("locations"):
            raise StoreError("目录缺少地点（data/locations/ 为空）。")

    # ---------- 通用读写 ----------
    def _path(self, kind: str, slug: str) -> Path:
        return self.root / "data" / kind / f"{slug}.md"

    def read(self, kind: str, slug: str) -> tuple[dict[str, Any], str] | None:
        """读取一篇文档，返回 (meta, body)。不存在返回 None。"""
        p = self._path(kind, slug)
        if not p.exists():
            return None
        return _parse_doc(p.read_text(encoding="utf-8"))

    def write(self, kind: str, slug: str, meta: dict[str, Any], body: str) -> Path:
        """写入文档（覆盖）。自动补生成时间戳。"""
        meta = {**meta}
        meta.setdefault("slug", slug)
        meta.setdefault("updated", datetime.now().strftime("%Y-%m-%d %H:%M"))
        p = self._path(kind, slug)
        p.write_text(_dump_doc(meta, body), encoding="utf-8")
        return p

    def append_body(self, kind: str, slug: str, chunk: str) -> None:
        """向文档正文末尾追加内容（不改 meta）。文件不存在则创建。"""
        p = self._path(kind, slug)
        if p.exists():
            _, body = _parse_doc(p.read_text(encoding="utf-8"))
            body = body.rstrip() + "\n\n" + chunk + "\n"
            p.write_text(_dump_doc({}, body), encoding="utf-8")
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
    def player_binding(self, user_id: str) -> str | None:
        """QQ → 角色 slug。"""
        d = self.read("players", str(user_id))
        return d[0].get("character_slug") if d else None

    def bind_player(self, user_id: str, char_slug: str, display_name: str = "") -> None:
        meta = {
            "qq": str(user_id),
            "character_slug": char_slug,
            "display_name": display_name,
            "permission": "玩家",
            "joined": datetime.now().strftime("%Y-%m-%d"),
        }
        self.write("players", str(user_id), meta, "")

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

    def char_scene(self, group_id: str, char_slug: str) -> str | None:
        s = self.get_session(group_id)
        return s.char_scene_map.get(char_slug)

    def set_char_scene(self, group_id: str, char_slug: str, scene_slug: str) -> None:
        s = self.get_session(group_id)
        s.char_scene_map[char_slug] = scene_slug
        self.save_session(s)
