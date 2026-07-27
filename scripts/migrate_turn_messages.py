"""迁移旧快照：为每个 turn 计算并添加 turn_messages（本轮增量消息）。

规则：
- messages[0] 固定为 system 提示词
- 第 N 轮的 turn_messages = 从第 N 个 user 消息开始到末尾
- 即跳过 system + 前 N-1 轮的完整回合
"""

import json
import sys
from pathlib import Path


def migrate_snapshots(snap_dir: Path) -> None:
    files = sorted(snap_dir.glob("*.json"))
    if not files:
        print("未找到快照文件")
        return

    print(f"找到 {len(files)} 个快照文件")

    for fp in files:
        snap = json.loads(fp.read_text(encoding="utf-8"))
        messages = snap.get("messages", [])

        if not messages:
            print(f"  {fp.name}: 空 messages，跳过")
            continue

        # 跳过 system 消息
        start = 1 if messages[0].get("role") == "system" else 0

        # 找到本轮起始 user 消息位置：倒数第一个 user 消息的索引
        turn_start = start
        for i in range(len(messages) - 1, start - 1, -1):
            if messages[i].get("role") == "user":
                turn_start = i
                break

        turn_msgs = messages[turn_start:]
        snap["turn_messages"] = turn_msgs

        fp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        print(f"  {fp.name}: turn_messages=[{turn_start}..{len(messages)-1}] ({len(turn_msgs)} 条)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python migrate_turn_messages.py <sessions/snapshots 目录>")
        sys.exit(1)

    snap_dir = Path(sys.argv[1])
    if not snap_dir.is_dir():
        print(f"目录不存在: {snap_dir}")
        sys.exit(1)

    migrate_snapshots(snap_dir)
    print("完成。")
