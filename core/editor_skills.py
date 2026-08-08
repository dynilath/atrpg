"""editor_skills.py --- 编辑助手 Skill 注册与调度系统。

将每种剧情要素（故事弧光、角色、NPC、物品、情景、地点、术语、状态记录）
拆分为独立的 skill，通过 subagent 模式调用，不再全量注入模板。

每个 skill 定义在 skills/editor-{type}/SKILL.md：
- 身份定义：专属于该内容类型的 AI 身份
- 专属模板：只包含该类型的 template
- 工具子集：指定该 skill 可用的工具
- 创建指南：该类内容的特定创建规范

使用方式：
    from core.editor_skills import load_skill, get_tool_subset, KIND_TO_SKILL

    skill = load_skill("story-arcs")
    system_prompt = skill.runtime_prompt  # 该 skill 专属的 system prompt
    tools = get_tool_subset("story-arcs") # 该 skill 可用的工具 schema 子集
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# Skill 与内容类型的映射
# =============================================================================

# content kind -> skill directory name
KIND_TO_SKILL: dict[str, str] = {
    "story-arcs":     "editor-story-arc",
    "characters":     "editor-character",
    "npcs":           "editor-npc",
    "items":          "editor-item",
    "scenes":         "editor-scene",
    "locations":      "editor-location",
    "terminology":    "editor-terminology",
    "state-records":  "editor-state-record",
}

# skill directory name -> content kind (反向映射)
SKILL_TO_KIND: dict[str, str] = {v: k for k, v in KIND_TO_SKILL.items()}

# 所有已注册的 editor skill 目录名
ALL_SKILLS: tuple[str, ...] = tuple(KIND_TO_SKILL.values())

# 内容类型的中文标签（用于 UI 展示）
KIND_LABELS: dict[str, str] = {
    "story-arcs":     "故事弧光",
    "characters":     "玩家角色",
    "npcs":           "NPC",
    "items":          "物品",
    "scenes":         "情景",
    "locations":      "地点",
    "terminology":    "设定术语",
    "state-records":  "状态记录",
}

# =============================================================================
# 每个 skill 可用的工具子集（工具名列表）
# =============================================================================

# 基础编辑工具：所有 skill 都需要
_BASE_TOOLS = frozenset({
    "read_doc", "write_doc", "patch_meta", "patch_body",
    "search_docs", "list_docs", "delete_doc", "rename_doc",
    "validate_doc", "normalize_doc",
})

# 批量工具：仅在全局操作时使用
_BATCH_TOOLS = frozenset({"validate_all", "normalize_all"})

# 上传文档分析工具：仅在聊天场景使用
_UPLOAD_TOOLS = frozenset({"read_upload", "search_upload", "analyze_upload"})

# 每种 skill 额外的专属工具（目前所有 skill 共享基础工具集 + 批量工具）
# 未来可按需扩展：如 story-arc 可增加 plan_arc 等
SKILL_TOOLS: dict[str, frozenset[str]] = {
    "story-arcs":     _BASE_TOOLS | _BATCH_TOOLS,
    "characters":     _BASE_TOOLS | _BATCH_TOOLS,
    "npcs":           _BASE_TOOLS | _BATCH_TOOLS,
    "items":          _BASE_TOOLS | _BATCH_TOOLS,
    "scenes":         _BASE_TOOLS | _BATCH_TOOLS,
    "locations":      _BASE_TOOLS | _BATCH_TOOLS,
    "terminology":    _BASE_TOOLS | _BATCH_TOOLS,
    "state-records":  _BASE_TOOLS | _BATCH_TOOLS,
}

# 编辑器聊天（通用路由）可用全部工具
_CHAT_TOOLS = _BASE_TOOLS | _BATCH_TOOLS | _UPLOAD_TOOLS


# =============================================================================
# Skill 数据结构
# =============================================================================

@dataclass
class EditorSkill:
    """一个编辑 skill 的完整定义。"""
    kind: str                                    # 内容类型（story-arcs 等）
    skill_dir: str                               # skill 目录名（editor-story-arc 等）
    label: str                                   # 中文标签
    runtime_prompt: str                          # 该 skill 专属的 system prompt
    template: str                                # 该 skill 专属的模板内容
    tool_names: frozenset[str] = field(default_factory=frozenset)  # 可用工具名集合

    @property
    def tools_description(self) -> str:
        """生成工具列表的可读描述（供 system prompt 使用）。"""
        return ", ".join(sorted(self.tool_names))


# =============================================================================
# Skill 加载
# =============================================================================

def _skills_root() -> Path:
    """skills/ 目录的绝对路径。"""
    return Path(__file__).resolve().parent.parent / "skills"


def _templates_root() -> Path:
    """templates/ 目录的绝对路径。"""
    return Path(__file__).resolve().parent.parent / "templates"


def _load_skill_md(skill_dir: str) -> str | None:
    """读取 skills/{skill_dir}/SKILL.md 的内容。"""
    p = _skills_root() / skill_dir / "SKILL.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"读取 {p} 失败: {e}")
    return None


def _load_template_for_kind(kind: str) -> str:
    """读取 templates/ 下对应类型的单一模板。"""
    tpl_map: dict[str, str | None] = {
        "story-arcs":     "story-arc.md",
        "characters":     "character.md",
        "npcs":           "npc.md",
        "items":          "item.md",
        "scenes":         "scene.md",
        "locations":      "location.md",
        "terminology":    "terminology.md",
        "state-records":  "state-record.md",
    }
    tpl_name = tpl_map.get(kind)
    if not tpl_name:
        return ""
    p = _templates_root() / tpl_name
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    return ""


# 缓存已加载的 skill
_skill_cache: dict[str, EditorSkill] = {}


def load_skill(kind: str, refresh: bool = False) -> EditorSkill | None:
    """加载指定内容类型的 skill。

    Args:
        kind: 内容类型（story-arcs, characters, npcs, ...）
        refresh: 是否强制重新加载（忽略缓存）

    Returns:
        EditorSkill 对象，或 None（unknown kind / skill 文件缺失）
    """
    if not refresh and kind in _skill_cache:
        return _skill_cache[kind]

    skill_dir = KIND_TO_SKILL.get(kind)
    if not skill_dir:
        logger.warning(f"未知内容类型 '{kind}'，无对应 skill")
        return None

    runtime = _load_skill_md(skill_dir)
    if not runtime:
        logger.warning(f"Skill '{skill_dir}' 的 SKILL.md 缺失，将回退到通用 editor_runtime.md")
        # 回退：尝试加载通用 editor runtime
        runtime = _load_fallback_runtime()

    template = _load_template_for_kind(kind)
    tool_names = SKILL_TOOLS.get(kind, _BASE_TOOLS)
    label = KIND_LABELS.get(kind, kind)

    skill = EditorSkill(
        kind=kind,
        skill_dir=skill_dir,
        label=label,
        runtime_prompt=runtime,
        template=template,
        tool_names=tool_names,
    )
    _skill_cache[kind] = skill
    return skill


def _load_fallback_runtime() -> str:
    """回退：加载通用 editor_runtime.md。"""
    p = Path(__file__).resolve().parent / "editor_runtime.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    return "你是 ATRPG 编辑助手，帮助用户创建和管理游戏素材。"


def load_all_skills(refresh: bool = False) -> dict[str, EditorSkill]:
    """加载所有 editor skill。

    Returns:
        {kind: EditorSkill} 字典，跳过错失的 skill
    """
    result: dict[str, EditorSkill] = {}
    for kind in KIND_TO_SKILL:
        skill = load_skill(kind, refresh=refresh)
        if skill:
            result[kind] = skill
    return result


def get_tool_subset(kind: str | None) -> list[dict[str, Any]]:
    """获取指定 skill 可用的工具 schema 子集。

    Args:
        kind: 内容类型，None 时返回全部聊天工具（通用路由场景）

    Returns:
        OpenAI function schema 列表
    """
    from .editor_tools import _EDITOR_REGISTRY

    if kind is None or kind not in SKILL_TOOLS:
        allowed = _CHAT_TOOLS
    else:
        allowed = SKILL_TOOLS.get(kind, _BASE_TOOLS)

    return [
        td.schema
        for name, td in _EDITOR_REGISTRY.items()
        if name in allowed
    ]


def get_chat_tools() -> list[dict[str, Any]]:
    """返回编辑器聊天的全部工具 schema（含上传文档分析）。"""
    from .editor_tools import _EDITOR_REGISTRY

    return [
        td.schema
        for name, td in _EDITOR_REGISTRY.items()
        if name in _CHAT_TOOLS
    ]


def build_skill_system_prompt(kind: str, existing_summary: str = "", upload_summary: str = "") -> str:
    """构建 skill subagent 的完整 system prompt。

    将 skill 专属 runtime prompt、模板、已有数据摘要、上传索引组合在一起。

    Args:
        kind: 内容类型
        existing_summary: 已有数据摘要
        upload_summary: 上传文档索引摘要

    Returns:
        完整的 system prompt 字符串
    """
    skill = load_skill(kind)
    if not skill:
        return ""

    parts = [skill.runtime_prompt]

    if skill.template:
        parts.append(f"\n## 模板参考\n\n{skill.template}")

    if existing_summary:
        parts.append(f"\n## 已有内容概况\n\n{existing_summary}")

    if upload_summary:
        parts.append(f"\n{upload_summary}")

    parts.append(f"\n## 可用工具\n\n本 skill 可用工具: {skill.tools_description}")

    return "\n".join(parts)


def discover_skills() -> list[str]:
    """扫描 skills/ 目录，发现所有 editor-* skill 目录。

    Returns:
        发现的 skill 目录名列表
    """
    root = _skills_root()
    if not root.exists():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and d.name.startswith("editor-") and (d / "SKILL.md").exists()
    )


def clear_cache() -> None:
    """清空 skill 缓存（测试用）。"""
    _skill_cache.clear()
