"""一次性迁移：旧 .atrpg/history/ → 新 .atrpg/sessions/

用法：python bot/migrate_to_sessions.py <game_dir> [old_session_key]

示例：
  python bot/migrate_to_sessions.py test_session/triangle_agency_test 73DBF47A18FDB3952E6216395D5F263F
"""

import sys
from pathlib import Path

# 确保 bot/atrpg_gm 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.atrpg_gm.db import migrate_history_to_sessions

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python bot/migrate_to_sessions.py <game_dir> [session_key]")
        sys.exit(1)

    game_dir = Path(sys.argv[1])
    session_key = sys.argv[2] if len(sys.argv) > 2 else "73DBF47A18FDB3952E6216395D5F263F"

    print(f"游戏目录: {game_dir}")
    print(f"迁移源:   .atrpg/history/{session_key}/")
    print(f"迁移目标: .atrpg/sessions/main/")
    print()

    count = migrate_history_to_sessions(game_dir, session_key)
    print(f"\n完成: {count} turns 已迁移")
