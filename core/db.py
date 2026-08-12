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

-- 消息表：每条 LLM 消息存一份（按 turn_node_id 分组），上下文从表重建。
-- 不含 system prefix（每轮单独加载，利用 API 前缀缓存）。
CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    turn_node_id  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
    seq           INTEGER NOT NULL,
    content       TEXT,
    tool_calls    TEXT,
    tool_call_id  TEXT,
    token_count   INTEGER DEFAULT 0,
    FOREIGN KEY (turn_node_id) REFERENCES tree_nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_msg_turn ON messages(turn_node_id, seq);
CREATE INDEX IF NOT EXISTS idx_msg_tool_call ON messages(tool_call_id);
"""


def _session_db(root: Path) -> Path:
    d = root / ".atrpg" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d / "main.db"


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


def _insert_turn_messages(conn: sqlite3.Connection, turn_node_id: str, messages: list[dict]) -> None:
    """批量插入一轮的增量消息到 messages 表（不含 system 消息）。"""
    for seq, msg in enumerate(messages):
        role = msg.get("role", "")
        if role == "system":
            continue  # system prefix 不入库，每轮单独加载
        tool_calls_json = None
        tcs = msg.get("tool_calls")
        if tcs:
            tool_calls_json = json.dumps(tcs, ensure_ascii=False)
        conn.execute(
            "INSERT INTO messages (id, turn_node_id, role, seq, content, tool_calls, tool_call_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                turn_node_id,
                role,
                seq,
                msg.get("content") or "",
                tool_calls_json,
                msg.get("tool_call_id") or None,
            ),
        )


def session_save_turn(
    root: Path,
    turn_messages: list[dict],
    meta: dict | None = None,
) -> dict:
    """保存一轮：在树中新增节点 + 插入本轮增量消息到 messages 表。

    turn_messages 是本轮新增的增量消息（不含 system prefix），
    完整上下文由 core.context.build_context() 从树 + 消息表重建。
    不再写 snapshot 文件 / current.json（消息粒度化存储替代快照冗余）。

    返回节点信息 {id, turn_no, branch_id, parent_id}。
    """
    db = _session_db(root)

    with sqlite3.connect(str(db)) as conn:
        branch_id = _ensure_active(root, conn)

        # 计算 turn_no
        row = conn.execute("SELECT MAX(turn_no) FROM tree_nodes").fetchone()
        turn_no = (row[0] or 0) + 1

        # 新增树节点
        node_id = uuid.uuid4().hex
        # parent = 当前活跃分支的 head
        cur_head = conn.execute(
            "SELECT head_id FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        parent_id = cur_head[0] if cur_head and cur_head[0] else None

        conn.execute(
            "INSERT INTO tree_nodes (id, parent_id, turn_no, snapshot_path, meta, branch_id) "
            "VALUES (?,?,?,?,?,?)",
            (node_id, parent_id, turn_no, None, json.dumps(meta or {}, ensure_ascii=False), branch_id),
        )
        # 插入本轮增量消息
        _insert_turn_messages(conn, node_id, turn_messages)
        # 更新分支 head
        conn.execute(
            "UPDATE branches SET head_id = ? WHERE id = ?", (node_id, branch_id)
        )
        conn.commit()

        logger.info(f"session save: turn={turn_no} branch={branch_id} node={node_id[:8]} msgs={len(turn_messages)}")
        return {"id": node_id, "turn_no": turn_no, "branch_id": branch_id, "parent_id": parent_id}


def session_load_head(root: Path) -> list[dict]:
    """加载活跃分支的完整消息（从树 + messages 表重建）。

    不再读 current.json / 快照文件——上下文始终与树状态一致。
    """
    from .context import build_context
    from .config import get_context_config

    cfg = get_context_config()
    return build_context(
        root,
        branch_id=session_get_active_branch(root),
        system_prefix="",
        window_keep=cfg.get("window_keep", 20),
        window_slide=cfg.get("window_slide", 5),
    )


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
                "llm_calls": meta.get("llm_calls", 0),
                "total_msgs": meta.get("total_msgs", 0),
                "branch_name": r["branch_name"] or "",
                "branch_id": r["branch_id"] or "",
            })
        return result


def session_get_turn_detail(root: Path, turn_id: str) -> dict | None:
    """获取某个 turn 的完整详情。

    messages（全量）: 从该节点反向走树 + messages 表重建（滑动窗口应用前）。
    turn_messages（增量）: 该 turn 节点的消息（messages 表按 seq 查询）。
    """
    db = _session_db(root)
    if not db.exists():
        return None

    from .context import walk_branch_to_root, query_turn_messages

    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, turn_no, parent_id, snapshot_path, meta FROM tree_nodes WHERE id = ?",
            (turn_id,),
        ).fetchone()
        if not row:
            return None

        # 父节点信息
        parent_turn_no = None
        parent_id = row["parent_id"]
        if parent_id:
            parent_row = conn.execute(
                "SELECT turn_no FROM tree_nodes WHERE id = ?", (parent_id,)
            ).fetchone()
            if parent_row:
                parent_turn_no = parent_row["turn_no"]

    # 增量消息（本轮）
    turn_messages = query_turn_messages(root, [turn_id])

    # 全量上下文：从该节点反向走树到 root，取全部消息（不应用滑动窗口）
    # walk_branch_to_root 需要从分支 head 出发；这里改为从节点反向走到根
    nodes: list[dict] = []
    node_id = turn_id
    with sqlite3.connect(str(db)) as conn:
        while node_id:
            n = conn.execute(
                "SELECT id, parent_id, turn_no FROM tree_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if not n:
                break
            nodes.append({"id": n[0], "parent_id": n[1], "turn_no": n[2]})
            node_id = n[1]
    nodes.reverse()  # 旧 → 新
    messages = query_turn_messages(root, [n["id"] for n in nodes])

    return {
        "id": row["id"],
        "turn_no": row["turn_no"],
        "parent_id": parent_id,
        "parent_turn_no": parent_turn_no,
        "messages": messages,
        "turn_messages": turn_messages,
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


def session_reset(root: Path, name: str | None = None) -> str:
    """重新开局：创建 head 为空的新分支并切换为活跃分支。

    新分支 head_id 为空 → walk_branch_to_root 返回 [] → build_context 得到空上下文，
    即抛弃旧主持人上下文、开始全新会话；旧轮次仍保留在树中可供回看。
    """
    db = _session_db(root)
    with sqlite3.connect(str(db)) as conn:
        _ensure_active(root, conn)  # 确保 active_branch 表存在
        branch_id = uuid.uuid4().hex[:8]
        branch_name = name or "重新开局"
        conn.execute(
            "INSERT INTO branches (id, name, head_id, created_at) VALUES (?,?,?,?)",
            (branch_id, branch_name, "", datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("UPDATE active_branch SET branch_id = ? WHERE id = 1", (branch_id,))
        conn.commit()
        logger.info(f"session reset: new branch {branch_name} ({branch_id})")
        return branch_id


def session_create_branch(root: Path, from_node_id: str, name: str | None = None) -> str | None:
    """从指定节点创建新分支（回滚点），返回新分支 id。

    消息粒度化存储后，上下文始终从树 + messages 表重建，
    无需再写 current.json——新分支的 head 指向该节点即可续接。
    """
    db = _session_db(root)
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute(
            "SELECT id, turn_no, snapshot_path FROM tree_nodes WHERE id = ?", (from_node_id,)
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
