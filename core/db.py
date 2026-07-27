"""db.py --- SQLite 持久化层。

两张数据库：
1. 聊天室: .atrpg/chat.db  →  messages 表
2. 会话树: .atrpg/sessions/main.db  →  tree_nodes / branches / active_branch 表

无 NoneBot 依赖，可被 server/ 和 bot/ 共享。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ===========================================================================
# 聊天室
# ===========================================================================

CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT    NOT NULL,
    sender   TEXT    NOT NULL,
    text     TEXT    NOT NULL,
    source   TEXT    NOT NULL DEFAULT 'web'
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
"""


def _chat_db(root: Path) -> Path:
    return root / ".atrpg" / "chat.db"


def init_chat(root: Path) -> None:
    """初始化聊天室数据库。"""
    db = _chat_db(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db)) as conn:
        conn.executescript(CHAT_SCHEMA)
        conn.commit()


def chat_append(root: Path, sender: str, text: str, source: str = "web") -> dict:
    """追加一条聊天消息，返回 {id, ts, ...}。"""
    ts = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(_chat_db(root))) as conn:
        cur = conn.execute(
            "INSERT INTO messages (ts, sender, text, source) VALUES (?,?,?,?)",
            (ts, sender, text, source),
        )
        conn.commit()
        return {"id": cur.lastrowid, "ts": ts, "sender": sender, "text": text, "source": source}


def chat_recent(root: Path, limit: int = 100) -> list[dict]:
    """读取最近 N 条消息。"""
    with sqlite3.connect(str(_chat_db(root))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ts, sender, text, source FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def chat_before(root: Path, before_id: int, limit: int = 50) -> list[dict]:
    """读取指定 id 之前的 N 条消息。"""
    with sqlite3.connect(str(_chat_db(root))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, ts, sender, text, source FROM messages WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# ===========================================================================
# 会话树 (open-webui 消息树模型)
# ===========================================================================

SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS tree_nodes (
    id            TEXT PRIMARY KEY,
    parent_id     TEXT,
    turn_no       INTEGER NOT NULL,
    snapshot_path TEXT,
    meta          TEXT,
    branch_id     TEXT DEFAULT '',
    FOREIGN KEY (parent_id) REFERENCES tree_nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_tree_parent ON tree_nodes(parent_id);

CREATE TABLE IF NOT EXISTS branches (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    head_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (head_id) REFERENCES tree_nodes(id)
);

CREATE TABLE IF NOT EXISTS active_branch (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    branch_id TEXT NOT NULL,
    FOREIGN KEY (branch_id) REFERENCES branches(id)
);
"""


def _session_db(root: Path) -> Path:
    d = root / ".atrpg" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d / "main.db"


def _snapshot_dir(root: Path) -> Path:
    d = root / ".atrpg" / "sessions" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def init_session(root: Path) -> None:
    """初始化会话树数据库。"""
    db = _session_db(root)
    with sqlite3.connect(str(db)) as conn:
        conn.executescript(SESSION_SCHEMA)
        # 兼容旧表：没有 branch_id 列的旧数据库
        try:
            conn.execute("SELECT branch_id FROM tree_nodes LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE tree_nodes ADD COLUMN branch_id TEXT DEFAULT ''")
        conn.commit()


def _ensure_active(root: Path, conn: sqlite3.Connection) -> str:
    """确保 active_branch 存在，返回当前活跃分支 id。"""
    row = conn.execute("SELECT branch_id FROM active_branch WHERE id = 1").fetchone()
    if row:
        return row[0]
    # 创建默认 main 分支
    branch_id = "main"
    conn.execute(
        "INSERT INTO branches (id, name, head_id, created_at) VALUES (?,?,?,?)",
        (branch_id, "默认", "", datetime.now(timezone.utc).isoformat()),
    )
    conn.execute("INSERT INTO active_branch (id, branch_id) VALUES (1, ?)", (branch_id,))
    return branch_id


def session_save_turn(
    root: Path,
    messages: list[dict],
    meta: dict | None = None,
) -> dict:
    """保存一轮：写快照文件 + 在树中新增节点，返回节点信息。"""
    sdir = _snapshot_dir(root)
    db = _session_db(root)

    with sqlite3.connect(str(db)) as conn:
        branch_id = _ensure_active(root, conn)

        # 计算 turn_no
        row = conn.execute("SELECT MAX(turn_no) FROM tree_nodes").fetchone()
        turn_no = (row[0] or 0) + 1

        # 写快照
        snap_path = sdir / f"{turn_no:03d}.json"
        snap = {
            "turn_no": turn_no,
            "timestamp": (meta or {}).get("timestamp", datetime.now(timezone.utc).isoformat()),
            "sender": (meta or {}).get("sender", ""),
            "player_text": (meta or {}).get("player_text", ""),
            "reply_preview": (meta or {}).get("reply_preview", ""),
            "usage": (meta or {}).get("usage", {}),
            "messages": messages,
        }
        snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

        # 新增树节点
        node_id = uuid.uuid4().hex
        # parent = 当前活跃分支的 head
        cur_head = conn.execute(
            "SELECT head_id FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        parent_id = cur_head[0] if cur_head and cur_head[0] else None

        conn.execute(
            "INSERT INTO tree_nodes (id, parent_id, turn_no, snapshot_path, meta, branch_id) VALUES (?,?,?,?,?,?)",
            (
                node_id,
                parent_id,
                turn_no,
                str(snap_path),
                json.dumps(meta or {}, ensure_ascii=False),
                branch_id,
            ),
        )
        # 更新分支 head
        conn.execute(
            "UPDATE branches SET head_id = ? WHERE id = ?", (node_id, branch_id)
        )
        conn.commit()

        logger.info(f"session save: turn={turn_no} branch={branch_id} node={node_id[:8]}")
        return {"id": node_id, "turn_no": turn_no, "branch_id": branch_id, "parent_id": parent_id}


def session_load_head(root: Path) -> list[dict]:
    """加载活跃分支的 messages（从 head 反向走到 root）。"""
    db = _session_db(root)
    if not db.exists():
        return []

    with sqlite3.connect(str(db)) as conn:
        branch_id = _ensure_active(root, conn)
        row = conn.execute(
            "SELECT head_id FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not row or not row[0]:
            return []

        # 反向遍历
        node_id = row[0]
        nodes: list[dict] = []
        while node_id:
            n = conn.execute(
                "SELECT id, parent_id, snapshot_path FROM tree_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if not n:
                break
            nodes.append({"id": n[0], "parent_id": n[1], "snapshot_path": n[2]})
            node_id = n[1]

        # 加载最后一个快照的 messages（即 head 的完整上下文）
        if nodes:
            snap_path = Path(nodes[0]["snapshot_path"])
            if snap_path.exists():
                data = json.loads(snap_path.read_text(encoding="utf-8"))
                return data.get("messages", [])

    return []


def session_list_turns(root: Path) -> list[dict]:
    """列出所有 turn 摘要（所有分支）。"""
    db = _session_db(root)
    if not db.exists():
        return []

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT t.id, t.turn_no, t.parent_id, t.meta, t.branch_id, "
            "b.name as branch_name, "
            "p.turn_no as parent_turn_no "
            "FROM tree_nodes t "
            "LEFT JOIN branches b ON b.id = t.branch_id "
            "LEFT JOIN tree_nodes p ON p.id = t.parent_id "
            "ORDER BY t.turn_no"
        ).fetchall()

        result = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r["meta"]) if r["meta"] else {}
            except json.JSONDecodeError:
                pass
            result.append({
                "id": r["id"],
                "turn_no": r["turn_no"],
                "parent_id": r["parent_id"],
                "parent_turn_no": r["parent_turn_no"],
                "sender": meta.get("sender", ""),
                "player_text": meta.get("player_text", ""),
                "reply_preview": meta.get("reply_preview", ""),
                "usage": meta.get("usage", {}),
                "branch_name": r["branch_name"] or "",
                "branch_id": r["branch_id"] or "",
            })
        return result


def session_get_turn_detail(root: Path, turn_id: str) -> dict | None:
    """获取某个 turn 的完整详情（含 messages 与父节点信息）。"""
    db = _session_db(root)
    if not db.exists():
        return None

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, turn_no, parent_id, snapshot_path, meta FROM tree_nodes WHERE id = ?",
            (turn_id,),
        ).fetchone()
        if not row:
            return None

        snap_path = Path(row["snapshot_path"])
        messages = []
        if snap_path.exists():
            data = json.loads(snap_path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])

        # 获取父节点信息
        parent_turn_no = None
        parent_id = row["parent_id"]
        if parent_id:
            parent_row = conn.execute(
                "SELECT turn_no FROM tree_nodes WHERE id = ?", (parent_id,)
            ).fetchone()
            if parent_row:
                parent_turn_no = parent_row["turn_no"]

        return {
            "id": row["id"],
            "turn_no": row["turn_no"],
            "parent_id": parent_id,
            "parent_turn_no": parent_turn_no,
            "messages": messages,
        }


def session_get_active_branch(root: Path) -> str:
    """返回当前活跃分支 id。"""
    db = _session_db(root)
    if not db.exists():
        init_session(root)
    with sqlite3.connect(str(db)) as conn:
        return _ensure_active(root, conn)


def session_get_branch_head(root: Path, branch_id: str) -> str | None:
    """返回指定分支的 head 节点 ID。"""
    db = _session_db(root)
    if not db.exists():
        return None
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT head_id FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        return row[0] if row else None


def session_switch_branch(root: Path, branch_id: str) -> bool:
    """切换到指定分支。"""
    db = _session_db(root)
    with sqlite3.connect(str(db)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not exists:
            return False
        conn.execute("UPDATE active_branch SET branch_id = ? WHERE id = 1", (branch_id,))
        conn.commit()
        logger.info(f"session switch branch: {branch_id}")
        return True


def session_create_branch(root: Path, from_node_id: str, name: str | None = None) -> str | None:
    """从指定节点创建新分支（回滚点），返回新分支 id。"""
    import uuid
    db = _session_db(root)
    with sqlite3.connect(str(db)) as conn:
        node = conn.execute(
            "SELECT id, turn_no FROM tree_nodes WHERE id = ?", (from_node_id,)
        ).fetchone()
        if not node:
            return None

        branch_id = str(uuid.uuid4())[:8]
        branch_name = name or f"分支 #{node[1]}"
        conn.execute(
            "INSERT INTO branches (id, name, head_id, created_at) VALUES (?,?,?,?)",
            (branch_id, branch_name, from_node_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("UPDATE active_branch SET branch_id = ? WHERE id = 1", (branch_id,))
        conn.commit()
        logger.info(f"session create branch: {branch_name} ({branch_id}) from node {from_node_id[:8]}")
        return branch_id


# ===========================================================================
# 数据迁移
# ===========================================================================

def migrate_history_to_sessions(root: Path, old_session_key: str) -> int:
    """将旧版 .atrpg/history/{key}/ 的快照迁移到新会话树结构。
    返回迁移的轮次数。
    """
    old_dir = root / ".atrpg" / "history" / old_session_key / "snapshots"
    if not old_dir.exists():
        logger.warning(f"旧历史目录不存在: {old_dir}")
        return 0

    init_session(root)

    snapshots = sorted(old_dir.glob("turn-*.json"))
    if not snapshots:
        return 0

    sdir = _snapshot_dir(root)
    db = _session_db(root)
    count = 0

    with sqlite3.connect(str(db)) as conn:
        branch_id = _ensure_active(root, conn)

        # 读 current.json 获取最新的 messages（作为最后一个 turn 的上下文）
        cur_file = root / ".atrpg" / "history" / old_session_key / "current.json"
        current_msgs = []
        if cur_file.exists():
            try:
                current_msgs = json.loads(cur_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        prev_node_id = None
        for snap_file in snapshots:
            try:
                snap = json.loads(snap_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            turn_no = snap.get("turn_no", count + 1)

            # 写快照到新位置
            new_path = sdir / snap_file.name
            snap["messages"] = snap.get("messages", [])
            new_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

            # 插入树节点
            node_id = uuid.uuid4().hex
            meta = {
                "timestamp": snap.get("timestamp", ""),
                "sender": snap.get("sender", ""),
                "player_text": snap.get("player_text", ""),
                "reply_preview": snap.get("reply_preview", ""),
                "usage": snap.get("usage", {}),
            }
            conn.execute(
                "INSERT INTO tree_nodes (id, parent_id, turn_no, snapshot_path, meta) VALUES (?,?,?,?,?)",
                (node_id, prev_node_id, turn_no, str(new_path), json.dumps(meta, ensure_ascii=False)),
            )
            prev_node_id = node_id
            count += 1

        # 更新分支 head
        if prev_node_id:
            conn.execute(
                "UPDATE branches SET head_id = ? WHERE id = ?", (prev_node_id, branch_id)
            )
            # 同时写 current 到最后一个快照
            if current_msgs and snapshots:
                last_snap = json.loads(snapshots[-1].read_text(encoding="utf-8"))
                last_snap["messages"] = current_msgs
                sdir_file = sdir / snapshots[-1].name
                sdir_file.write_text(json.dumps(last_snap, ensure_ascii=False), encoding="utf-8")

        conn.commit()

    logger.info(f"迁移完成: {old_session_key} -> sessions/main, {count} turns")
    return count
