"""query.py --- 上传文档检索 / 按需读取（CLI 薄壳）。

用法:
    python query.py <upload_dir> search <关键词> [--file <txt名>] [--limit N]
    python query.py <upload_dir> read <txt名> [--offset N] [--length N] [--section <章节关键词>]

服务端通过编辑器工具（search_upload / read_upload）提供相同能力；
本脚本用于调试与手动维护。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core import doc_analysis  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="上传文档检索 / 按需读取")
    parser.add_argument("upload_dir", help="uploads 目录（通常为 <游戏目录>/.atrpg/uploads）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="关键词检索")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--file", default="", help="限定文件（txt 名或原始文件名）")
    p_search.add_argument("--limit", type=int, default=5)

    p_read = sub.add_parser("read", help="读取片段")
    p_read.add_argument("filename", help="txt 名或原始文件名")
    p_read.add_argument("--offset", type=int, default=0)
    p_read.add_argument("--length", type=int, default=4000)
    p_read.add_argument("--section", default="", help="章节关键词")

    args = parser.parse_args()
    upload_dir = Path(args.upload_dir)
    if not upload_dir.is_dir():
        print(f"错误: 目录不存在 {upload_dir}")
        sys.exit(1)

    if args.command == "search":
        print(doc_analysis.search(upload_dir, args.query, args.file, args.limit))
    elif args.command == "read":
        print(doc_analysis.read_section(
            upload_dir, args.filename, args.offset, args.length, args.section,
        ))


if __name__ == "__main__":
    main()
