"""migrate_history.py — 把旧的扁平历史文件迁移到新的快照结构。

旧结构：<game-dir>/.atrpg/history/<session>.json  （扁平 messages 数组）
新结构：<game-dir>/.atrpg/history/<session>/
         ├── current.json          当前活跃历史（截断版）
         └── snapshots/
             ├── turn-001.json     每轮快照（完整 messages + meta）
             └── ...

轮次切分：以 role=="user" 的消息作为新轮开始，该 user 之前的所有消息归入上一轮。
首轮若没有 user（如被截断），则把开头到第一个 user 之前归为第 1 轮。

用法：python migrate_history.py <game-dir>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def split_turns(msgs: list[dict]) -> list[list[dict]]:
    """按 user 消息切分轮次。每轮含从上一个 user（或开头）到下一个 user 之前的所有消息。"""
    turns: list[list[dict]] = []
    current: list[dict] = []
    for m in msgs:
        current.append(m)
        if m.get("role") == "user":
            # user 消息标志着本轮的"玩家发言"，但本轮的 assistant 回复在 user 之后
            # 所以不能在这里切——要等到下一个 user 才切
            pass
    # 实际切分：找所有 user 的位置，在 user 处开新轮
    # 但 user 后面跟着 assistant 回复，属于同一轮
    # 所以：第一个 user 之前的消息（system + 可能的残留）归第 1 轮
    # 每个 user 到下一个 user 之前为一轮
    turns = []
    current = []
    for m in msgs:
        if m.get("role") == "user" and current:
            # 遇到新 user，把之前积累的作为一轮
            turns.append(current)
            current = []
        current.append(m)
    if current:
        turns.append(current)
    return turns


def extract_meta(turn_no: int, turn_msgs: list[dict]) -> dict:
    """从轮次消息中提取元信息。"""
    sender = ""
    player_text = ""
    reply_preview = ""
    for m in turn_msgs:
        if m.get("role") == "user":
            content = m.get("content", "") or ""
            if 'sender="' in content:
                sender = content.split('sender="')[1].split('"')[0]
            # 提取 </turn> 前的正文
            if "</turn>" in content:
                text_part = content.split("</turn>")[0]
                # 取最后一个 \n\n 之后的部分作为玩家文本
                if "\n\n" in text_part:
                    player_text = text_part.rsplit("\n\n", 1)[-1]
                else:
                    player_text = text_part
            else:
                player_text = content
            player_text = player_text.strip()[:120]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if tc.get("function", {}).get("name") == "reply":
                    args_str = tc.get("function", {}).get("arguments", "")
                    try:
                        args = json.loads(args_str) if args_str else {}
                        reply_preview = (args.get("content", "") or "")[:120]
                    except json.JSONDecodeError:
                        pass
    return {
        "turn_no": turn_no,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender,
        "player_text": player_text,
        "reply_preview": reply_preview,
        "usage": {},
    }


def migrate(game_dir: str) -> None:
    root = Path(game_dir).resolve()
    hdir = root / ".atrpg" / "history"
    if not hdir.exists():
        print(f"历史目录不存在: {hdir}")
        return

    # 找所有扁平 .json 文件（不是子目录）
    flat_files = [p for p in hdir.iterdir() if p.is_file() and p.suffix == ".json"]
    if not flat_files:
        print("没有扁平历史文件需要迁移")
        return

    for fp in flat_files:
        session_key = fp.stem
        print(f"\n迁移 session: {session_key}")

        try:
            msgs = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  跳过（JSON 解析失败）: {e}")
            continue

        turns = split_turns(msgs)
        print(f"  消息总数: {len(msgs)}, 切分为 {len(turns)} 轮")

        # 创建新目录结构
        sdir = hdir / session_key
        snap_dir = sdir / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)

        # 每轮保存快照（完整 messages 累积版）
        accumulated = []
        for i, turn_msgs in enumerate(turns, 1):
            accumulated.extend(turn_msgs)
            meta = extract_meta(i, turn_msgs)
            snap = {**meta, "messages": list(accumulated)}
            snap_path = snap_dir / f"turn-{i:03d}.json"
            snap_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
            print(f"  turn-{i:03d}: {meta['sender']} | {meta['player_text'][:40]}")

        # current.json = 最后一轮的完整 messages
        (sdir / "current.json").write_text(
            json.dumps(accumulated, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  current.json 已写入（{len(accumulated)} 条消息）")

        # 删除旧扁平文件
        fp.unlink()
        print(f"  旧文件 {fp.name} 已删除")

    print("\n✓ 迁移完成")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python migrate_history.py <game-dir>")
        sys.exit(1)
    migrate(sys.argv[1])
