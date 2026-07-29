"""【已废弃】为所有镜头过场文件添加角色状态段。

⚠️ 此脚本用于向 scene 文件批量添加"## 在场角色状态"表格（旧格式）。
该格式已于 2026-07-28 废弃：角色当前状态改为维护在角色数据文件的 frontmatter 字段中
（current_location / current_status / equipment），不再在 scene 中表格化维护。
保留此脚本仅作历史参考，不应再次运行。
"""
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from core.store import _parse_doc, _dump_doc

sd = PROJECT / "test_session" / "triangle_agency_test_2" / "data" / "scenes"

scene_states = {
    "2026-07-24_2215-triad-branch-office-briefing-begin": {
        "time": "2026-07-24 22:15",
        "attendees": ["lin-mo", "miller", "gm-zhao"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 简报室靠门第二把折叠椅 | 新入职，叼着没点的烟，等待任务 | 标准收容手提箱 III 型 |\n"
            "| 米勒 | 林默对面椅子上 | 新入职，帽子不离身，刚自我介绍 | 标准收容手提箱 III 型 |\n"
            "| 赵正源(GM) | 白板前 | 正在下达任务简报 | -- |"
        ),
    },
    "2026-07-24_2229-triad-branch-office-break-room": {
        "time": "2026-07-24 22:29",
        "attendees": ["lin-mo", "lao-zheng"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 茶水间折叠桌旁 | 新入职，向老郑讨教入门经验 | -- |\n"
            "| 老郑 | 靠窗台，手里夹着烟 | 资深特工/半退休，给新人传授机构生存法则 | 保温杯 |"
        ),
    },
    "2026-07-24_2256-triad-branch-office-briefing-5c": {
        "time": "2026-07-24 22:56",
        "attendees": ["lin-mo", "zhaolei"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 靠墙的椅子 | 第一个到场，吸第三根烟，等待简报 | 标准收容手提箱 III 型 |\n"
            "| 赵蕾 | 刚推门进来 | 确认角色卡后首次进入简报室，初识林默 | -- |"
        ),
    },
    "2026-07-24_2303-triad-branch-office-equipment": {
        "time": "2026-07-24 23:03",
        "attendees": ["lin-mo", "miller", "lao-hu"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 器材窗口前 | 急迫，猛敲玻璃 | 刚领：收容手提箱 III 型、波纹手枪 Mark II、认知阻尼器 |\n"
            "| 米勒 | 林默旁边 | 等装备，准备出发 | 同上 |\n"
            "| 老胡 | 防爆玻璃后 | 被敲门吓到，保温杯差点洒 | 老式收音机 |"
        ),
    },
    "2026-07-24_2303-perfect-corner-pizza-arrival": {
        "time": "2026-07-24 23:03",
        "attendees": ["lin-mo", "miller"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 槐树街47号正门口，后绕至后巷 | 抵达现场，吸第三根烟后开始侦查 | 收容手提箱、波纹手枪、认知阻尼器 |\n"
            "| 米勒 | 卷帘门前 | 用意大利语朝二楼喊话，正门叫门 | 同上 |"
        ),
    },
    "2026-07-24_2329-perfect-corner-pizza-back-alley": {
        "time": "2026-07-24 23:29",
        "attendees": ["lin-mo", "miller"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 林默 | 后巷纱窗破洞旁 | 蹲着观察二楼，灰雾感知异常体状态 | 收容手提箱、波纹手枪、认知阻尼器 |\n"
            "| 米勒 | 后巷，刚翻墙进来 | 踩着牛奶箱翻入，落地踩碎纸板 | 波纹手枪 Mark II（已拔出） |"
        ),
    },
    "2026-07-25_0016-perfect-corner-pizza-rossi-room": {
        "time": "2026-07-25 00:16",
        "attendees": ["miller", "marco-rossi"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 米勒 | 二楼房间中央，后冲下楼梯 | 持枪对峙，开火后冲下一楼 | 波纹手枪 Mark II（已发射一次） |\n"
            "| 马尔科·罗西 | 瘫坐在地板 / 后爬至楼梯口 | 抱亡妻相框痛哭，崩溃 | -- |"
        ),
    },
    "2026-07-25_0021-perfect-corner-pizza-kitchen-confront": {
        "time": "2026-07-25 00:21",
        "attendees": ["miller"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 米勒 | 一楼后厨烤炉前 | 正面对峙异常体拉玛萨，质问焦点 | 波纹手枪 Mark II（余弹1-2发）、认知阻尼器 |\n"
            "| 拉玛萨(异常体) | 烤炉前，后撤退至炉内 | 核心焦点暴露，从威胁态转乞求态 | -- |\n"
            "| 马尔科·罗西 | 楼梯顶端 | 趴着向下看，哭着求不要碰她 | -- |"
        ),
    },
    "2026-07-26_2220-triad-branch-office-equipment-zhaolei": {
        "time": "2026-07-26 22:20",
        "attendees": ["zhaolei", "lao-hu"],
        "char_state": (
            "| 角色 | 位置 | 状态 | 持有/装备 |\n"
            "|------|------|------|------------|\n"
            "| 赵蕾 | 器材窗口前 | 从简报室下来，等待申领外勤装备 | -- |\n"
            "| 老胡 | 防爆玻璃后 | 低头擦手提箱，收音机播交通广播 | -- |"
        ),
    },
}

for slug, info in scene_states.items():
    fp = sd / f"{slug}.md"
    if not fp.exists():
        print(f"  MISS {slug}")
        continue
    meta, body = _parse_doc(fp.read_text(encoding="utf-8"))
    meta["time"] = info["time"]
    meta["attendees"] = info["attendees"]
    char_section = f"\n\n## 在场角色状态\n\n{info['char_state']}\n"

    if "## 在场角色状态" not in body:
        bg_marker = "## 背景"
        if bg_marker in body:
            idx = body.index(bg_marker)
            next_section = body.find("\n## ", idx + len(bg_marker))
            if next_section == -1:
                next_section = len(body)
            body = body[:next_section] + char_section + body[next_section:]
        else:
            body += char_section

    fp.write_text(_dump_doc(meta, body), encoding="utf-8")
    print(f"  OK {slug}")

print("Done")
