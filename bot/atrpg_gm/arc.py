"""arc.py — 弧光分级规划与追踪。

分级（尺度从小到大）：
  次要局部 < 单局 < 主要
主持人可规划前两级，主要弧光由备团用户预置、只跑+追踪。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Store

__all__ = ["ArcError", "MAJOR", "ONE_SHOT", "MINOR", "Arc", "plan_arc", "track_arc", "balance_report"]

MAJOR = "主要"          # 备团用户预置，主持人不可规划
ONE_SHOT = "单局"        # 主持人可规划（任务/冒险，1~3 次聚会）
MINOR = "次要局部"       # 主持人可规划（单场景局部互动，可不收尾）

# 并行阈值
LIMITS = {MAJOR: 2, ONE_SHOT: 3, MINOR: 3}


class ArcError(Exception):
    """弧光操作越权或失败。"""


@dataclass
class Arc:
    slug: str
    level: str
    planner: str
    status: str
    current_stage: str
    title: str

    @classmethod
    def from_meta(cls, slug: str, meta: dict[str, Any]) -> "Arc":
        return cls(
            slug=slug,
            level=meta.get("级别", ""),
            planner=meta.get("规划者", ""),
            status=meta.get("状态", "进行中"),
            current_stage=meta.get("当前阶段", "启程"),
            title=meta.get("名称", slug),
        )


def _check_red_lines(meta: dict[str, Any]) -> str | None:
    """检查新弧光是否触及「高层次」红线（命中即主要，主持人不得规划）。
    返回命中原因或 None。"""
    scope = (meta.get("影响范围") or "").lower()
    if any(k in scope for k in ("核心npc", "阵营", "势力")):
        return "引入核心 NPC 阵营/势力"
    if any(k in scope for k in ("政权", "灾害", "神祇", "世界状态")):
        return "改变世界基调或状态"
    span = meta.get("跨度", "")
    if "多场" in str(span) or "跨" in str(span):
        return "体量超出单局"
    if meta.get("级别") == MAJOR:
        return "级别标注为主要"
    return None


def balance_report(store: "Store") -> dict[str, int]:
    """当前进行中弧光的并行计数。"""
    counts = {MAJOR: 0, ONE_SHOT: 0, MINOR: 0}
    for d in store.list_docs("story-arcs"):
        if d["meta"].get("状态") == "进行中":
            lv = d["meta"].get("级别", MINOR)
            counts[lv] = counts.get(lv, 0) + 1
    return counts


def plan_arc(
    store: "Store",
    slug: str,
    level: str,
    title: str,
    hook: str,
    body: str,
    meta_extra: dict[str, Any] | None = None,
) -> str:
    """主持人规划一条次要局部/单局弧光。

    落盘到 data/story-arcs/<slug>.md，头部标注级别/规划者/来源/平衡检查。
    违规则抛 ArcError。
    """
    if level == MAJOR:
        raise ArcError("主持人不可规划主要弧光（高层次弧光由备团用户预置）")

    red = _check_red_lines(meta_extra or {})
    if red:
        raise ArcError(f"触及高层次红线：{red}，该弧光应为主要，主持人不得规划")

    counts = balance_report(store)
    if counts.get(level, 0) >= LIMITS[level]:
        raise ArcError(f"{level}弧光并行已达上限{LIMITS[level]}，过载，请克制或结束既有弧光")

    meta: dict[str, Any] = {
        "名称": title,
        "slug": slug,
        "级别": level,
        "规划者": "主持人",
        "来源": "涌现",
        "状态": "进行中",
        "当前阶段": "启程",
        "平衡检查": {
            "与主要冲突": "否",
            "当前并行": counts,
            "过载风险": "否",
        },
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if meta_extra:
        meta.update(meta_extra)

    arc_body = f"## 一句话梗概\n{hook}\n\n## 四阶段设计（主持人规划）\n{body}\n"
    store.write("story-arcs", slug, meta, arc_body)
    return slug


def track_arc(store: "Store", arc_slug: str, state_slug: str, note: str, new_stage: str | None = None) -> None:
    """追踪主要（或自建）弧光的阶段推进。

    - 在弧光「状态变化记录」段追加引用
    - 可选更新「当前阶段」指针
    - 不改写四阶段设计蓝图
    """
    d = store.read("story-arcs", arc_slug)
    if d is None:
        raise ArcError(f"弧光不存在: {arc_slug}")
    meta, body = d
    stamp = datetime.now().strftime("%Y-%m-%d")
    line = f"- {stamp} [{state_slug}] — {note}"
    if new_stage:
        meta["当前阶段"] = new_stage

    # 追加到「状态变化记录」段；若无则新建
    marker = "## 状态变化记录"
    if marker in body:
        body = body.split(marker, 1)[0] + marker + body.split(marker, 1)[1].split("\n## ", 1)[0] + "\n" + line + "\n"
    else:
        body = body.rstrip() + f"\n\n{marker}\n{line}\n"

    store.write("story-arcs", arc_slug, meta, body)


def end_arc(store: "Store", arc_slug: str, reason: str = "") -> None:
    """标记弧光结束/搁置（不改写蓝图，仅改状态字段）。"""
    d = store.read("story-arcs", arc_slug)
    if d is None:
        raise ArcError(f"弧光不存在: {arc_slug}")
    meta, body = d
    meta["状态"] = "已结束" if "结束" in reason else "搁置"
    store.write("story-arcs", arc_slug, meta, body)
