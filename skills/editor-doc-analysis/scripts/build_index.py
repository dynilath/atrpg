"""build_index.py --- 重建上传文档索引（CLI 薄壳）。

用法:
    python build_index.py <upload_dir>

<upload_dir> 通常为 <游戏目录>/.atrpg/uploads

服务端在每次上传/删除后会自动刷新索引；本脚本用于手动重建（如索引损坏时）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从任意工作目录运行：定位到项目根（skills/editor-doc-analysis/scripts -> 项目根）
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.doc_analysis import build_index, index_summary  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python build_index.py <upload_dir>")
        sys.exit(1)

    upload_dir = Path(sys.argv[1])
    if not upload_dir.is_dir():
        print(f"错误: 目录不存在 {upload_dir}")
        sys.exit(1)

    idx = build_index(upload_dir)
    files = idx.get("files", [])
    print(f"已构建索引: {len(files)} 个文件 -> {upload_dir / 'index.json'}")
    summary = index_summary(upload_dir)
    if summary:
        print("\n" + summary)


if __name__ == "__main__":
    main()
