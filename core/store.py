"""store.py --- TRPG 上下文目录加载与持久化。

吃一个符合 agent.md 规划的目录，提供统一的读写接口。
启动时校验：至少 1 条主要弧光 + 若干场景/地点，否则拒绝开团。

线程/进程安全：Store 使用基于文件创建原子性的跨平台文件锁
（.atrpg/.lock），保护 write/append_body/save_history 等写操作。
多进程（如 NoneBot QQ + 独立 Web API 并行）可安全共享 data/ 目录。
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
        "sessions",
        "players",
    )

    def __init__(self, game_dir: str | Path):
        self.root = Path(game_dir).resolve()
        if not self.root.is_dir():
            raise StoreError(f"游戏目录不存在: {self.root}")
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

    def _init_databases(self) -> None:
        """初始化 SQLite 数据库（聊天室 + 会话树）。"""
        from . import db as _db
        try:
            _db.init_chat(self.root)
            _db.init_session(self.root)
        except Exception:
            logger.warning("数据库初始化失败（可能已存在）", exc_info=True)

    def _validate(self) -> None:
        """启动校验：必须有「世界基础材料」。

        接受两种形式之一：
        - data/world-book.md（经 build_world_book.py 总结的常驻世界书，推荐）
        - 根目录下的 .txt/.md 原始材料（pdf_extract 等，未预处理时回退）

        弧光/场景/地点都不强制——没有预置主要弧光也能开团，主持人可现场即兴规划
        单局/局部弧光；场景/地点按需由 LLM 生成。但世界基础材料是 LLM 主持人的
        世界知识来源，缺了它无法基于规则书带团。
        """
        if not (self.root / "data" / "world-book.md").exists() and not self.list_world_material():
            raise StoreError(
                "目录缺少「世界基础材料」：需 data/world-book.md（推荐，用 build_world_book.py 生成）"
                "或根目录下至少 1 个 .txt/.md 原始材料文件。"
            )

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
        content = _dump_doc(meta, body)
        with _FileLock(self.root / ".atrpg" / ".lock"):
            p.write_text(content, encoding="utf-8")
        logger.debug(f"store write: {kind}/{slug} body={len(body)}chars")
        return p

    def append_body(self, kind: str, slug: str, chunk: str) -> None:
        """向文档正文末尾追加内容（不改 meta）。文件不存在则创建。"""
        p = self._path(kind, slug)
        if p.exists():
            with _FileLock(self.root / ".atrpg" / ".lock"):
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
    def _session_dir(self, session_key: str) -> Path:
        return self.root / ".atrpg" / "history" / session_key

    def load_history(self, session_key: str) -> list[dict[str, Any]]:
        """加载某会话的 LLM 对话历史（从 current.json）。不存在返回空列表。

        加载时清洗孤立 tool 消息。
        """
        import json
        cur = self._session_dir(session_key) / "current.json"
        if not cur.exists():
            return []
        try:
            msgs = json.loads(cur.read_text(encoding="utf-8"))
            logger.debug(f"store load_history: {session_key} msgs={len(msgs)}")
        except (json.JSONDecodeError, OSError):
            return []
        return self._clean_messages(msgs)

    @staticmethod
    def _clean_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """清洗孤立 tool 消息：保留 assistant(tool_calls) → tool(result) 完整配对。"""
        cleaned: list[dict[str, Any]] = []
        pending_call_ids: set[str] = set()
        for m in msgs:
            role = m.get("role", "")
            if role == "assistant" and m.get("tool_calls"):
                cleaned.append(m)
                pending_call_ids = {tc.get("id", "") for tc in m["tool_calls"]}
            elif role == "tool":
                tcid = m.get("tool_call_id", "")
                if tcid in pending_call_ids:
                    cleaned.append(m)
                    pending_call_ids.discard(tcid)
            else:
                pending_call_ids.clear()
                cleaned.append(m)
        return cleaned

    def _truncate(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """截断历史（保留首条 system + 最近若干条），保证 tool_calls/tool 配对完整。"""
        MAX = 40
        KEEP_RECENT = 20
        if len(messages) <= MAX:
            return messages
        head = messages[:1]
        cut = len(messages) - KEEP_RECENT
        while cut < len(messages):
            msg = messages[cut]
            role = msg.get("role", "")
            if role == "tool" or (role == "assistant" and msg.get("tool_calls")):
                cut += 1
                continue
            break
        tail = messages[cut:]
        return head + [{"role": "system", "content": "（较早的对话已省略）"}] + tail

    def save_history(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
        meta: dict[str, Any] | None = None,
    ) -> None:
        """保存对话历史：先快照完整版到 snapshots/，再写截断版到 current.json。

        meta 含本轮元信息（turn_no/timestamp/sender/player_text/reply_preview/usage），
        与完整 messages 一起存进快照，供控制台展示与回滚。
        """
        import json
        sdir = self._session_dir(session_key)
        snap_dir = sdir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)

        # 计算轮次号
        existing = sorted(snap_dir.glob("turn-*.json"))
        turn_no = len(existing) + 1

        # 快照：完整未截断 messages + meta
        snap = {
            "turn_no": turn_no,
            "timestamp": (meta or {}).get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "sender": (meta or {}).get("sender", ""),
            "player_text": (meta or {}).get("player_text", ""),
            "reply_preview": (meta or {}).get("reply_preview", ""),
            "usage": (meta or {}).get("usage", {}),
            "messages": messages,
        }
        with _FileLock(self.root / ".atrpg" / ".lock"):
            (snap_dir / f"turn-{turn_no:03d}.json").write_text(
                json.dumps(snap, ensure_ascii=False), encoding="utf-8"
            )
            # current.json：截断版（供下轮 LLM 续接）
            cur = sdir / "current.json"
            cur.write_text(json.dumps(self._truncate(messages), ensure_ascii=False), encoding="utf-8")
        logger.debug(
            f"store save_history: {session_key} turn={turn_no} msgs={len(messages)}"
        )

    def list_sessions(self) -> list[str]:
        """列出所有有历史的 session key。"""
        hdir = self.root / ".atrpg" / "history"
        if not hdir.exists():
            return []
        sessions = []
        for p in sorted(hdir.iterdir()):
            if p.is_dir() and (p / "current.json").exists():
                sessions.append(p.name)
        return sessions

    def list_turns(self, session_key: str) -> list[dict[str, Any]]:
        """列出某 session 的所有轮次摘要（不含 messages 正文）。"""
        import json
        snap_dir = self._session_dir(session_key) / "snapshots"
        if not snap_dir.exists():
            return []
        turns = []
        for p in sorted(snap_dir.glob("turn-*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                turns.append({
                    "turn_no": d.get("turn_no"),
                    "timestamp": d.get("timestamp", ""),
                    "sender": d.get("sender", ""),
                    "player_text": d.get("player_text", ""),
                    "reply_preview": d.get("reply_preview", ""),
                    "usage": d.get("usage") or {},
                })
            except (json.JSONDecodeError, OSError):
                continue
        return turns

    def usage_summary(self, session_key: str) -> dict[str, Any]:
        """汇总某 session 的总用量（累加所有轮次）。"""
        turns = self.list_turns(session_key)
        total = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "turns_with_usage": 0, "turns_total": len(turns)}
        for t in turns:
            u = t.get("usage") or {}
            if u:
                total["prompt_tokens"] += u.get("prompt_tokens", 0)
                total["completion_tokens"] += u.get("completion_tokens", 0)
                total["cached_tokens"] += u.get("cached_tokens", 0)
                total["turns_with_usage"] += 1
        return total

    def get_turn_detail(self, session_key: str, turn_no: int) -> dict[str, Any] | None:
        """读取某轮快照的完整内容（含 messages）。"""
        import json
        p = self._session_dir(session_key) / "snapshots" / f"turn-{turn_no:03d}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def rollback(self, session_key: str, turn_no: int) -> bool:
        """回滚到某轮：删除该轮之后的快照，把该轮的 messages 写回 current.json。

        回滚到 turn_no 意味着保留 turn_no 及之前的对话，丢弃之后的。
        """
        import json
        sdir = self._session_dir(session_key)
        snap_dir = sdir / "snapshots"
        target = snap_dir / f"turn-{turn_no:03d}.json"
        if not target.exists():
            return False
        try:
            d = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        with _FileLock(self.root / ".atrpg" / ".lock"):
            # 删除之后的快照
            for p in sorted(snap_dir.glob("turn-*.json")):
                name = p.stem  # turn-NNN
                n = int(name.split("-")[1])
                if n > turn_no:
                    p.unlink()
            # 把该轮 messages（截断版）写回 current.json
            (sdir / "current.json").write_text(
                json.dumps(self._truncate(d["messages"]), ensure_ascii=False), encoding="utf-8"
            )
        return True

    # ---------- 位置追踪 ----------
    def chars_in_scene(self, scene_slug: str) -> list[str]:
        """查某场景有哪些角色（读场景 meta「在场者」字段，反向查询）。"""
        d = self.read("scenes", scene_slug)
        if d is None:
            return []
        return d[0].get("在场者", []) or []

    def all_char_locations(self, group_id: str) -> dict[str, str]:
        """列出某会话所有角色的当前位置（角色 slug → 场景 slug）。"""
        s = self.get_session(group_id)
        return dict(s.char_scene_map)

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
        # 兼容旧 data/players/
        d = self.read("players", str(user_id))
        if d and d[0].get("character_slug") and d[0].get("character_slug") != "none":
            return d[0].get("character_slug")
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

    def char_scene(self, group_id: str, char_slug: str) -> str | None:
        s = self.get_session(group_id)
        return s.char_scene_map.get(char_slug)

    def set_char_scene(self, group_id: str, char_slug: str, scene_slug: str) -> None:
        s = self.get_session(group_id)
        s.char_scene_map[char_slug] = scene_slug
        self.save_session(s)
