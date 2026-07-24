"""build_world_book.py — 世界书预处理脚本（开发阶段单次任务）。

读取游戏目录下的世界材料文件（pdf_extract_*.txt 等），调 LLM 总结成结构化
世界书，输出到 <game-dir>/data/world-book.md（带 front matter）。

世界书是数据源（非缓存），作为 LLM 主持人的常驻世界观知识，类似 SillyTavern
的常驻世界书。生成后由 store.read_world_book() 读取，进入 system prompt 稳定前缀。

用法：
    python build_world_book.py <game-dir>
    python build_world_book.py <game-dir> --max-chars 40000   # 限制喂给 LLM 的原文长度
"""

from __future__ import annotations

import asyncio
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

# 世界书分节结构（LLM 按此组织输出）
WORLD_BOOK_SECTIONS = [
    "## 世界观概述",
    "## 主要阵营与势力",
    "## 核心规则机制",
    "## 关键术语",
    "## 重要地点",
    "## 典型 NPC 类型",
]

SUMMARY_PROMPT = """你是一个 TRPG 世界设定整理助手。下面是从规则书 PDF 提取的原始文本（可能含 OCR 噪声、页码、目录等）。
请把它整理成一份结构化的世界书，供 AI 主持人作为常驻世界观知识使用。

要求：
1. 按以下分节组织（缺则省略该节，不要编造原文没有的内容）：
{sections}

2. 每节用简洁的条目式描述，保留关键设定（阵营关系、规则机制、术语定义、地点特征等）。
3. 去除页码、目录、OCR 噪声等无关内容。
4. 保持客观，忠实于原文；不确定的地方标注「（原文未详述）」。
5. 输出纯 Markdown 正文，不要加外层标题（front matter 由脚本处理）。

原始文本：
---
{material}
---
"""


# 文风参考生成 prompt：从规则书的叙事性段落提取文风特征与样本
STYLE_PROMPT = """你是一个 TRPG 文风分析助手。下面是从规则书 PDF 提取的原始文本。
请从中提取该规则书的「文风参考」，供 AI 主持人模仿其叙事调性。

要求：
1. 先分析整体文风特征（语气、幽默感、叙事视角、用词偏好等），用 3-5 条概括。
2. 从原文中摘抄 5-8 段最能体现文风的叙事性段落（不是规则/术语条目，而是带描写、带态度、带叙事感的段落），每段标注出处页码（若有）。
3. 若原文有明显的「机构公文腔」「冷幽默」「黑色幽默」等调性，重点保留。
4. 给出 3 条「文风模仿要点」：主持人在演绎 NPC 台词、场景描写、裁决旁白时应遵循的语气指南。
5. 输出纯 Markdown 正文，按以下分节：
## 文风特征
## 文风样本（摘抄）
## 文风模仿要点

原始文本：
---
{material}
---
"""


def load_llm_config() -> dict:
    """从 config.toml 读 LLM 配置（不依赖 nonebot）。"""
    cfg_path = Path(__file__).resolve().parent / "config.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)
    return cfg["atrpg"]


def collect_material(game_dir: Path, max_chars: int) -> str:
    """收集并拼接世界材料文件（pdf_extract_*.txt 及其他根目录 txt/md）。"""
    excluded = {"agent.md", "project.md", "readme.md"}
    files = []
    for p in sorted(game_dir.glob("*.txt")):
        files.append(p)
    for p in sorted(game_dir.glob("*.md")):
        if p.name.lower() not in excluded:
            files.append(p)

    if not files:
        raise SystemExit(f"错误：{game_dir} 下未找到世界材料文件（.txt/.md）")

    parts = []
    total = 0
    for p in files:
        text = p.read_text(encoding="utf-8")
        if total + len(text) > max_chars:
            remain = max_chars - total
            if remain > 500:
                parts.append(f"=== {p.name}（截断）===\n{text[:remain]}")
            break
        parts.append(f"=== {p.name} ===\n{text}")
        total += len(text)
    return "\n\n".join(parts)


async def generate_world_book(material: str, cfg: dict) -> str:
    """调 LLM 生成世界书正文。"""
    client = AsyncOpenAI(base_url=cfg["llm_base_url"], api_key=cfg["llm_api_key"])
    sections = "\n".join(WORLD_BOOK_SECTIONS)
    prompt = SUMMARY_PROMPT.format(sections=sections, material=material)

    print(f"调用 LLM ({cfg['llm_model']}) 生成世界书... 原文 {len(material)} 字")
    resp = await client.chat.completions.create(
        model=cfg["llm_model"],
        messages=[
            {"role": "system", "content": "你是 TRPG 世界设定整理助手，擅长从杂乱文本提取结构化设定。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    content = resp.choices[0].message.content or ""
    usage = resp.usage
    if usage:
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        print(f"LLM 用量: prompt={usage.prompt_tokens} cached={cached} completion={usage.completion_tokens}")
    return content.strip()


def write_world_book(game_dir: Path, body: str) -> Path:
    """写 data/world-book.md（带 front matter）。"""
    import yaml

    meta = {
        "名称": "世界书",
        "类型": "世界书",
        "来源": "由 build_world_book.py 从 pdf_extract 总结生成",
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    out = game_dir / "data" / "world-book.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"---\n{front}\n---\n\n# 世界书\n\n{body}\n", encoding="utf-8")
    return out


async def generate_style_guide(material: str, cfg: dict) -> str:
    """调 LLM 从规则书叙事性段落提取文风参考。"""
    client = AsyncOpenAI(base_url=cfg["llm_base_url"], api_key=cfg["llm_api_key"])
    prompt = STYLE_PROMPT.format(material=material)

    print(f"调用 LLM ({cfg['llm_model']}) 生成文风参考... 原文 {len(material)} 字")
    resp = await client.chat.completions.create(
        model=cfg["llm_model"],
        messages=[
            {"role": "system", "content": "你是 TRPG 文风分析助手，擅长识别规则书的叙事调性并提取可模仿的文风样本。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    content = resp.choices[0].message.content or ""
    usage = resp.usage
    if usage:
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        print(f"LLM 用量: prompt={usage.prompt_tokens} cached={cached} completion={usage.completion_tokens}")
    return content.strip()


def write_style_guide(game_dir: Path, body: str) -> Path:
    """写 data/style-guide.md（带 front matter）。"""
    import yaml

    meta = {
        "名称": "文风参考",
        "类型": "文风参考",
        "来源": "由 build_world_book.py 从 pdf_extract 叙事段落提取",
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    out = game_dir / "data" / "style-guide.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"---\n{front}\n---\n\n# 文风参考\n\n{body}\n", encoding="utf-8")
    return out


async def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python build_world_book.py <game-dir> [--max-chars N]")
        return 1

    game_dir = Path(sys.argv[1]).resolve()
    if not game_dir.is_dir():
        print(f"错误：目录不存在 {game_dir}")
        return 1

    max_chars = 40000
    if "--max-chars" in sys.argv:
        idx = sys.argv.index("--max-chars")
        max_chars = int(sys.argv[idx + 1])

    cfg = load_llm_config()
    material = collect_material(game_dir, max_chars)
    print(f"收集到材料 {len(material)} 字")

    body = await generate_world_book(material, cfg)
    out = write_world_book(game_dir, body)
    print(f"\n✓ 世界书已生成：{out}（{len(body)} 字）")

    style = await generate_style_guide(material, cfg)
    style_out = write_style_guide(game_dir, style)
    print(f"✓ 文风参考已生成：{style_out}（{len(style)} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
