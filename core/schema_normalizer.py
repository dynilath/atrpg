"""schema_normalizer.py --- 自动修复 front matter。

根据 schema 定义，自动补全默认值、修正枚举值格式、
从 Markdown 正文提取信息补全 meta。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import schemas


@dataclass
class Change:
    """单条修改记录。"""
    field: str
    old_value: Any
    new_value: Any
    source: str  # "default" | "enum_fix" | "body_extract" | "cleanup"


@dataclass
class NormalizeResult:
    """规范化结果。"""
    meta: dict[str, Any]
    changes: list[Change] = field(default_factory=list)


# ===========================================================================
# 枚举值模糊匹配表
# ===========================================================================

_ENUM_FIX_TABLE: dict[str, dict[str, str]] = {
    # 通用
    "type": {
        "npc": "NPC",
        "pc": "玩家角色",
        "player": "玩家角色",
        "character": "玩家角色",
    },
    "status": {
        "active": "进行中",
        "ongoing": "进行中",
        "ended": "已结束",
        "paused": "搁置（待续）",
        "pending": "待确认",
        "confirmed": "正式",
        "draft": "草案",
        "retired": "退场",
    },
    "level": {
        "major": "主要",
        "one_shot": "单局",
        "oneshot": "单局",
        "minor": "次要局部",
        "main": "主要",
        "arc": "单局",
    },
    "current_stage": {
        "departure": "启程",
        "introduction": "启程",
        "rising_action": "矛盾积累",
        "conflict": "矛盾积累",
        "climax": "高潮",
        "resolution": "新的稳定",
    },
    "planner": {
        "director": "备团用户",
        "gm": "主持人",
        "host": "主持人",
    },
    "source": {
        "preset": "预置",
        "emergent": "涌现",
        "emergence": "涌现",
        "player": "玩家驱动",
        "editor": "备团编辑",
    },
    "nature": {
        "support": "支撑剧情",
        "main": "主线",
        "temp": "临时生成",
        "recyclable": "可回收",
        "villain": "反派",
        "ally": "盟友",
        "neutral": "中立",
        "key": "关键道具",
        "clue": "线索",
        "consumable": "消耗品",
        "equipment": "装备",
        "decoration": "装饰",
    },
    "change_type": {  # state-records 的 type 字段（schema 里也叫 type）
        "relation": "关系变化",
        "item": "物品获得",
        "state": "状态改变",
        "info": "信息揭露",
        "other": "其他",
    },
}


def _fuzzy_match_enum(value: str, allowed: list[str]) -> str | None:
    """尝试将非标准枚举值模糊匹配到允许值。"""
    value_lower = value.strip().lower()

    # 精确匹配（忽略大小写）
    for a in allowed:
        if a.lower() == value_lower:
            return a

    # 查找所有模糊匹配表
    for table in _ENUM_FIX_TABLE.values():
        if value_lower in table:
            fixed = table[value_lower]
            if fixed in allowed:
                return fixed

    return None


# ===========================================================================
# Body → Meta 提取规则
# ===========================================================================

def _extract_from_body(body: str, kind: str) -> dict[str, Any]:
    """从 Markdown 正文中提取信息补全 front matter。"""
    result: dict[str, Any] = {}

    if kind == "scenes":
        # 从 "## Front matter" 或 "## 在场角色" 之前的段落提取
        for heading in ("## Front matter", "## 在场角色", "## 背景", "## 场景描写"):
            section = _extract_section(body, heading)
            if not section:
                continue
            for line in section.split("\n"):
                line = line.strip()
                # "- **name**：<值>" 或 "- name：<值>"
                if line.startswith("-"):
                    for key in ("name", "nature", "location", "time"):
                        for fmt in (f"**{key}**：", f"**{key}**:", f"{key}：", f"{key}:"):
                            if fmt in line:
                                val = line.split(fmt, 1)[-1].strip()
                                if val and val != f"<{key}>" and not val.startswith("<"):
                                    result[key] = val
            break  # 只处理第一个匹配的段落

    elif kind == "story-arcs":
        section = _extract_section(body, "## 概览")
        if section:
            for line in section.split("\n"):
                line = line.strip()
                if line.startswith("-"):
                    for key, display in [
                        ("level", "级别"), ("planner", "规划者"), ("source", "来源"),
                        ("current_stage", "当前阶段"), ("status", "状态"), ("hook", "一句话梗概"),
                    ]:
                        for fmt in (f"**{display}**：", f"**{display}**:", f"{display}：", f"{display}:"):
                            if fmt in line:
                                val = line.split(fmt, 1)[-1].strip()
                                if val and val != f"<{display}>" and not val.startswith("<"):
                                    result[key] = val

    elif kind in ("characters", "npcs"):
        section = _extract_section(body, "## 基础信息")
        if section:
            for line in section.split("\n"):
                line = line.strip()
                if line.startswith("-"):
                    for key, display in [
                        ("identity", "身份"), ("appearance", "外貌"),
                        ("personality", "性格"), ("age", "年龄"),
                        ("speaking_style", "说话风格"),
                    ]:
                        for fmt in (f"**{display}**：", f"**{display}**:", f"{display}：", f"{display}:"):
                            if fmt in line:
                                val = line.split(fmt, 1)[-1].strip()
                                if val and val != f"<{display}>" and not val.startswith("<"):
                                    result[key] = val

    return result


def _extract_section(body: str, heading: str) -> str | None:
    """提取某个 Markdown 标题下的内容（直到下一个同级或更高级标题）。"""
    if heading not in body:
        return None
    idx = body.index(heading)
    start = idx + len(heading)
    tail = body[start:]

    # 找到下一个 ## 或 # 标题
    next_heading = None
    for line in tail.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("###"):
            next_heading = tail.index(line)
            break

    if next_heading is not None:
        return tail[:next_heading].strip()
    return tail.strip()


# ===========================================================================
# 主函数
# ===========================================================================


def normalize(meta: dict[str, Any], body: str, kind: str,
              fill_defaults: bool = True,
              fix_enums: bool = True,
              extract_from_body: bool = True,
              clean_system_fields: bool = True,
              ) -> NormalizeResult:
    """根据 schema 自动修复 front matter。

    Args:
        meta:  当前 front matter 字典
        body:  Markdown 正文
        kind:  文档类型
        fill_defaults:      为缺失必填/可选字段填入默认值
        fix_enums:          修正非标准枚举值
        extract_from_body:  从正文提取信息补全 meta
        clean_system_fields: 删除 front matter 中的 slug/updated 等系统字段

    Returns:
        NormalizeResult（修改后的 meta + 变更记录）
    """
    schema = schemas.SCHEMAS.get(kind, {})
    changes: list[Change] = []
    meta = dict(meta)  # 不修改原始 dict

    # ---- 1. 清理系统字段 ----
    if clean_system_fields:
        for sys_field in schemas.SYSTEM_FIELDS:
            if sys_field in meta:
                old_val = meta.pop(sys_field)
                changes.append(Change(
                    field=sys_field, old_value=old_val, new_value=None,
                    source="cleanup",
                ))

    # ---- 2. 填入默认值 ----
    if fill_defaults:
        for field, default_val in schema.get("defaults", {}).items():
            current = meta.get(field)
            if current is None or (isinstance(current, str) and not current.strip()):
                meta[field] = default_val
                changes.append(Change(
                    field=field, old_value=current, new_value=default_val,
                    source="default",
                ))

    # ---- 3. 枚举值修正 ----
    if fix_enums:
        for field, spec in schema.get("fields", {}).items():
            if spec["type"] != "enum":
                continue
            val = meta.get(field)
            if val is None or not isinstance(val, str) or not val.strip():
                continue
            if val not in spec["values"]:
                fixed = _fuzzy_match_enum(val, spec["values"])
                if fixed:
                    meta[field] = fixed
                    changes.append(Change(
                        field=field, old_value=val, new_value=fixed,
                        source="enum_fix",
                    ))

    # ---- 4. 从 body 提取 ----
    if extract_from_body:
        extracted = _extract_from_body(body, kind)
        for field, value in extracted.items():
            current = meta.get(field)
            if current is None or (isinstance(current, str) and not current.strip()):
                meta[field] = value
                changes.append(Change(
                    field=field, old_value=current, new_value=value,
                    source="body_extract",
                ))

    return NormalizeResult(meta=meta, changes=changes)
