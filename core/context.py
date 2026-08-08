"""context.py --- LLM 上下文重建与滑动窗口管理。

消息粒度化存储：对话消息逐条存入 SQLite messages 表（按 turn_node_id 分组），
每次处理玩家消息时从树 + 消息表重建上下文，不再依赖 current.json / 快照文件。

阶梯式滑动窗口：对话轮数超过 window_keep 后，每累计 window_slide 轮
滑掉最早 window_slide 轮（以完整 turn 为边界），控制上下文长度。
滑出的旧轮中，世界状态变化已由工具调用写入 data/ 文档（front matter），
AI 可通过 query_memory 等工具按需获取，不依赖对话历史。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


# ===========================================================================
# 树遍历
# ===========================================================================

def walk_branch_to_root(root: Path, branch_id: str = "main") -> list[dict]:
    """从分支 head 反向走到 root，返回节点列表。

    返回顺序：[head, parent, ..., root]（最新在前）。
    每个节点: {id, turn_no, parent_id}。
    """
    db = root / ".atrpg" / "sessions" / "main.db"
    if not db.exists():
        return []

    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT head_id FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not row or not row[0]:
            return []

        nodes: list[dict] = []
        node_id = row[0]
        while node_id:
            n = conn.execute(
                "SELECT id, parent_id, turn_no FROM tree_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if not n:
                break
            nodes.append({"id": n[0], "parent_id": n[1], "turn_no": n[2]})
            node_id = n[1]
    return nodes


# ===========================================================================
# 阶梯式滑动窗口
# ===========================================================================

def apply_sliding_window(
    nodes: list[dict],
    window_keep: int = 20,
    window_slide: int = 5,
) -> list[dict]:
    """阶梯式滑动窗口：保留最近 window_keep 轮，超出后每 window_slide 轮滑动一次。

    nodes 顺序: [head, ..., root]（最新在前）。

    算法：
      total = len(nodes)
      if total <= keep: 全部保留
      excess = total - keep
      slides = excess // slide   （向下取整，阶梯式：未凑够 slide 不滑）
      skip = slides * slide
      返回 nodes[:total - skip]，即保留最近 (total - skip) 轮。

    示例 (keep=20, slide=5):
      total=20 → 保留 20 轮
      total=21 → excess=1, slides=0 → 保留 21 轮（未达滑动阈值）
      total=24 → excess=4, slides=0 → 保留 24 轮
      total=25 → excess=5, slides=1, skip=5 → 保留 20 轮
      total=29 → excess=9, slides=1, skip=5 → 保留 24 轮
      total=30 → excess=10, slides=2, skip=10 → 保留 20 轮
    """
    if window_keep <= 0 or window_slide <= 0:
        return nodes
    total = len(nodes)
    if total <= window_keep:
        return nodes
    excess = total - window_keep
    slides = excess // window_slide
    skip = slides * window_slide
    if skip <= 0:
        return nodes
    result = nodes[: total - skip]
    logger.info(
        f"滑动窗口: total={total} keep={window_keep} slide={window_slide} "
        f"skip={skip} -> 保留 {len(result)} 轮 (turn {result[-1]['turn_no']}~{result[0]['turn_no']})"
    )
    return result


# ===========================================================================
# 消息查询
# ===========================================================================

def query_turn_messages(root: Path, turn_node_ids: list[str]) -> list[dict]:
    """从 messages 表拉取指定 turn 节点的消息，按轮次升序 + seq 升序。

    返回 OpenAI 兼容的消息字典列表（不含 system 消息）。
    孤立 tool 消息（无配对 assistant tool_calls）在此被过滤。
    """
    if not turn_node_ids:
        return []
    db = root / ".atrpg" / "sessions" / "main.db"
    if not db.exists():
        return []

    # 记录每个 turn_node_id 的 turn_no，用于排序
    turn_order: dict[str, int] = {}
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT id, turn_no FROM tree_nodes WHERE id IN (%s)"
            % ",".join("?" * len(turn_node_ids)),
            turn_node_ids,
        ).fetchall()
        turn_order = {r[0]: r[1] for r in rows}

    placeholders = ",".join("?" * len(turn_node_ids))
    with sqlite3.connect(str(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT turn_node_id, seq, role, content, tool_calls, tool_call_id "
            f"FROM messages WHERE turn_node_id IN ({placeholders}) "
            f"ORDER BY turn_node_id, seq",
            turn_node_ids,
        ).fetchall()

    # 组装 + 清洗：只保留 assistant(tool_calls) → tool 完整配对
    msgs: list[dict] = []
    pending_call_ids: set[str] = set()
    for r in sorted(rows, key=lambda r: (turn_order.get(r["turn_node_id"], 0), r["seq"])):
        role = r["role"]
        if role == "assistant" and r["tool_calls"]:
            try:
                tcs = json.loads(r["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                tcs = []
            msgs.append({"role": "assistant", "content": r["content"] or "", "tool_calls": tcs})
            pending_call_ids = {tc.get("id", "") for tc in tcs}
        elif role == "tool":
            tcid = r["tool_call_id"] or ""
            if tcid in pending_call_ids:
                msgs.append({"role": "tool", "tool_call_id": tcid, "content": r["content"] or ""})
                pending_call_ids.discard(tcid)
        else:
            pending_call_ids.clear()
            msgs.append({"role": role, "content": r["content"] or ""})
    return msgs


# ===========================================================================
# 上下文重建
# ===========================================================================

def build_context(
    root: Path,
    branch_id: str = "main",
    system_prefix: str = "",
    window_keep: int = 20,
    window_slide: int = 5,
) -> list[dict]:
    """重建 LLM 上下文：树遍历 + 滑动窗口 + 消息表查询。

    返回 [system_prefix 消息] + 窗口内全部对话消息。
    system_prefix 为空时返回不含 system 的消息列表（供 load_history 兼容）。
    """
    nodes = walk_branch_to_root(root, branch_id)
    if not nodes:
        return [{"role": "system", "content": system_prefix}] if system_prefix else []

    window_nodes = apply_sliding_window(nodes, window_keep, window_slide)
    # 从旧到新排序，便于按 turn_no 排序查询
    node_ids = [n["id"] for n in reversed(window_nodes)]
    msgs = query_turn_messages(root, node_ids)

    if system_prefix:
        return [{"role": "system", "content": system_prefix}] + msgs
    return msgs
