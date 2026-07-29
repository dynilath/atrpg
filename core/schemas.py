"""schemas.py --- 文档类型 schema 定义。

每种文档类型定义：required 必填字段、fields 字段规范（类型/枚举值）、
defaults 默认值、body_sections 期望的 Markdown 章节、cross_refs 跨文件引用。
"""

from __future__ import annotations

# ===========================================================================
# Schema 注册表
# ===========================================================================

SCHEMAS: dict[str, dict] = {}

# --- 玩家角色 ---

SCHEMAS["characters"] = {
    "required": ["name", "type"],
    "fields": {
        "name":            {"type": "str"},
        "type":            {"type": "enum", "values": ["玩家角色", "NPC"]},
        "identity":        {"type": "str"},
        "appearance":      {"type": "str"},
        "personality":     {"type": "str"},
        "background":      {"type": "str"},
        "speaking_style":  {"type": "str"},
        "skills":          {"type": "str"},
        "equipment":       {"type": "list", "item_type": "str"},
        "color":           {"type": "int", "range": [0, 360]},
        "status":          {"type": "enum", "values": ["待确认", "正式", "退场"]},
        "current_location":   {"type": "str"},
        "current_status":  {"type": "str"},
        "owner_openid":    {"type": "str"},
    },
    "defaults": {
        "type": "玩家角色",
        "status": "待确认",
    },
    "body_sections": ["基础信息", "性格与背景", "能力与资源", "剧情连接"],
}

# --- NPC ---

SCHEMAS["npcs"] = {
    "required": ["name", "type", "nature"],
    "fields": {
        "name":            {"type": "str"},
        "type":            {"type": "enum", "values": ["玩家角色", "NPC"]},
        "nature":          {"type": "enum", "values": ["反派", "盟友", "中立", "支撑剧情", "临时"]},
        "identity":        {"type": "str"},
        "brief":           {"type": "str"},
        "appearance":      {"type": "str"},
        "personality":     {"type": "str"},
        "speaking_style":  {"type": "str"},
        "current_location":   {"type": "str"},
    },
    "defaults": {
        "type": "NPC",
        "nature": "支撑剧情",
    },
    "body_sections": ["基础信息", "性格与背景", "与其他角色关系", "所知信息"],
}

# --- 故事弧光 ---

SCHEMAS["story-arcs"] = {
    "required": ["name", "level", "current_stage", "status"],
    "fields": {
        "name":          {"type": "str"},
        "level":         {"type": "enum", "values": ["主要", "单局", "次要局部"]},
        "planner":       {"type": "enum", "values": ["备团用户", "主持人"]},
        "source":        {"type": "enum", "values": ["预置", "涌现", "玩家驱动", "备团编辑"]},
        "current_stage": {"type": "enum", "values": ["启程", "矛盾积累", "高潮", "新的稳定"]},
        "status":        {"type": "enum", "values": ["草案", "进行中", "已结束", "搁置（待续）"]},
        "hook":          {"type": "str"},
        "scope":         {"type": "str"},
        "related":       {"type": "str"},
        "created":       {"type": "str"},
    },
    "defaults": {
        "level": "单局",
        "planner": "备团用户",
        "source": "备团编辑",
        "current_stage": "启程",
        "status": "草案",
    },
    "body_sections": ["概览", "平衡检查", "四阶段设计", "关联要素", "状态变化记录"],
}

# --- 情景 ---

SCHEMAS["scenes"] = {
    "required": ["name", "nature", "location"],
    "fields": {
        "name":      {"type": "str"},
        "nature":    {"type": "enum", "values": ["主线", "临时生成", "可回收", "支撑剧情 / 可回收"]},
        "location":  {"type": "str"},
        "time":      {"type": "str"},
        "attendees": {"type": "list", "item_type": "str"},
    },
    "defaults": {
        "nature": "可回收",
    },
    "body_sections": ["在场角色", "背景", "事件推进", "镜头结束状态"],
    "cross_refs": {
        "location": "locations",
    },
}

# --- 地点 ---

SCHEMAS["locations"] = {
    "required": ["name"],
    "fields": {
        "name":        {"type": "str"},
        "type":        {"type": "str"},
        "description": {"type": "str"},
    },
    "defaults": {
        "type": "一般地点",
    },
}

# --- 道具 ---

SCHEMAS["items"] = {
    "required": ["name", "nature"],
    "fields": {
        "name":       {"type": "str"},
        "nature":     {"type": "enum", "values": ["关键道具", "线索", "消耗品", "装备", "装饰", "支撑剧情"]},
        "holder":     {"type": "str"},
        "appearance": {"type": "str"},
        "source":     {"type": "str"},
        "usage":      {"type": "str"},
    },
    "defaults": {
        "nature": "支撑剧情",
    },
    "body_sections": ["外观", "来源", "持有者", "用途", "剧情意义"],
}

# --- 状态记录 ---

SCHEMAS["state-records"] = {
    "required": ["date", "title", "type"],
    "fields": {
        "date":  {"type": "str"},
        "title": {"type": "str"},
        "type":  {"type": "enum", "values": ["关系变化", "物品获得", "状态改变", "信息揭露", "其他"]},
    },
    "defaults": {},
    "body_sections": ["概要", "连接信息", "详细"],
}

# --- 设定术语 ---

SCHEMAS["terminology"] = {
    "required": ["term", "brief"],
    "fields": {
        "term":     {"type": "str"},
        "aliases":  {"type": "str"},
        "category": {"type": "str"},
        "brief":    {"type": "str"},
    },
    "defaults": {
        "category": "其他",
    },
    "body_sections": ["详细解释", "关联术语", "来源"],
}

# ===========================================================================
# 系统字段（不在 front matter 中存储，由代码层管理）
# ===========================================================================

SYSTEM_FIELDS = frozenset({"slug", "updated"})

# slug: 文件名去掉 .md 后缀，唯一标识
# updated: 由 store.write() 自动设置的最后修改时间
