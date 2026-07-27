"""迁移脚本：将 data/ 下所有 .md 文件的 YAML front matter 中文键转英文键。

用法：
    cd H:/gitrepo/atrpg
    python scripts/migrate_front_matter.py <游戏目录>

示例：
    python scripts/migrate_front_matter.py test_session/triangle_agency_test
    python scripts/migrate_front_matter.py bot/example-game

特性：
    - 读取旧文件 → 翻译中文键 → 写回（覆盖）
    - _parse_doc 自动处理翻译，_dump_doc 写出英文键
    - 迁移前自动备份到 .atrpg/backup-frontmatter/
    - 非 .md 文件跳过
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.store import _parse_doc, _dump_doc


def migrate_game_dir(game_dir: Path) -> dict:
    """迁移单个游戏目录，返回统计信息。"""
    data_root = game_dir / "data"
    if not data_root.is_dir():
        print(f"⚠ 跳过 {game_dir}：无 data/ 子目录")
        return {"skipped": True}

    # 备份
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = game_dir / ".atrpg" / "backup-frontmatter" / timestamp
    backup_dir.parent.mkdir(parents=True, exist_ok=True)

    md_files = list(data_root.rglob("*.md"))
    if not md_files:
        print(f"ℹ {game_dir}：无 .md 文件，跳过")
        return {"skipped": True, "file_count": 0}

    print(f"📁 处理 {game_dir}，发现 {len(md_files)} 个 .md 文件")

    stats = {"total": len(md_files), "translated": 0, "unchanged": 0, "errors": 0}
    for fp in md_files:
        try:
            rel = fp.relative_to(game_dir)
            text = fp.read_text(encoding="utf-8")
            meta, body = _parse_doc(text)

            # 检查是否仅包含非 _FIELD_MAP 键（即已是英文或不需要翻译）
            has_chinese = any(
                k for k, v in __import__("yaml").safe_load(
                    _DOC_RE_pat.match(text).group(1) or ""
                ).items() if k in _FIELD_MAP_pat
            ) if _DOC_RE_pat.match(text) else False

            # 始终用 _dump_doc 重写以确保统一（即使没有中文键也标准化格式）
            new_text = _dump_doc(meta, body)

            if new_text != text:
                # 备份
                rel_backup = backup_dir / rel
                rel_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, rel_backup)

                fp.write_text(new_text, encoding="utf-8")
                stats["translated"] += 1
                print(f"  ✓ {rel} — 字段已翻译")
            else:
                stats["unchanged"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ✗ {fp.relative_to(game_dir)} — 错误: {e}")

    # 清理空备份目录
    if stats["translated"] == 0:
        shutil.rmtree(backup_dir, ignore_errors=True)
    else:
        print(f"\n📦 备份已存至: {backup_dir}")

    return stats


# 为 _parse_doc 复用预定义的正则和字段映射
_DOC_RE_pat = __import__("re").compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", __import__("re").DOTALL)
_FIELD_MAP_pat = {
    "名称": "name", "姓名": "name", "标题": "title", "术语": "term",
    "类型": "type", "性质": "nature", "身份": "identity", "状态": "status",
    "级别": "level", "类别": "category", "简要定义": "brief", "一句话梗概": "hook",
    "日期": "date", "来源": "source", "所属": "parent", "基调": "tone",
    "规划者": "planner", "当前阶段": "current_stage", "关联要素": "related",
    "影响范围": "scope", "跨度": "span", "弧光名称": "arc_title",
    "地点": "location", "在场者": "attendees", "当前场景": "current_scene",
    "道具": "items",
}


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/migrate_front_matter.py <游戏目录> [游戏目录...]")
        print("示例: python scripts/migrate_front_matter.py test_session/triangle_agency_test")
        sys.exit(1)

    all_stats = {}
    for arg in sys.argv[1:]:
        game_dir = Path(arg).resolve()
        if not game_dir.is_dir():
            print(f"✗ 目录不存在: {game_dir}")
            continue
        stats = migrate_game_dir(game_dir)
        all_stats[str(game_dir)] = stats

    # 汇总
    print("\n" + "=" * 50)
    total_files = sum(s.get("total", 0) for s in all_stats.values())
    total_translated = sum(s.get("translated", 0) for s in all_stats.values())
    total_errors = sum(s.get("errors", 0) for s in all_stats.values())
    print(f"完成：{len(all_stats)} 个目录，{total_files} 个文件")
    print(f"  已翻译: {total_translated}")
    print(f"  未变化: {sum(s.get('unchanged', 0) for s in all_stats.values())}")
    if total_errors:
        print(f"  错误: {total_errors}")
    print(f"\n迁移后的文件已写入英文字段名。")
    print(f"系统 `_parse_doc` 已内置兼容——旧中文键仍可被读取，但新写一律用英文。")


if __name__ == "__main__":
    main()
