"""验证迁移后的 front matter 兼容性（仅测试无外部依赖的模块）。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.store import Store, _parse_doc, _dump_doc, _FIELD_MAP
print("core.store: OK")
from core.arc import balance_report, _normalize_level
print("core.arc: OK")
print(f"Field map has {len(_FIELD_MAP)} entries")

print()
print("=== 2. Verify migrated files parse correctly ===")
store = Store(str(PROJECT_ROOT / "test_session/triangle_agency_test"))

# Character
char = store.read("characters", "林默")
assert char is not None
meta, body = char
assert meta.get("name") == "林默", f"Expected 林默, got {meta.get('name')}"
assert meta.get("status") == "正式"
assert meta.get("type") == "玩家角色"
print(f"Character 林默: name={meta.get('name')}, status={meta.get('status')}, type={meta.get('type')}")

# Location - check any existing location
locs = store.list_docs("locations")
if locs:
    loc = store.read("locations", locs[0]["slug"])
    assert loc is not None
    meta, _ = loc
    print(f"Location {locs[0]['slug']}: name={meta.get('name')}, type={meta.get('type', 'N/A')}")
else:
    print("No locations found in test_session — skipping location check")

# Scene - check for English key 'attendees' (empty list)
sc = store.read("scenes", "briefing-room-5c")
assert sc is not None
meta, _ = sc
assert "attendees" in meta
assert isinstance(meta["attendees"], list)
print(f"Scene briefing-room-5c: name={meta.get('name')}, location={meta.get('location')}, attendees={meta.get('attendees')}")

# chars_in_scene still works with English key
print(f"chars_in_scene(briefing-room-5c): {store.chars_in_scene('briefing-room-5c')}")

# Arc
arc = store.read("story-arcs", "perfect-pizza-arc")
assert arc is not None
meta, _ = arc
assert meta.get("name") == "完美披萨"
assert meta.get("level") in ("主要", "单局", "次要局部")
assert meta.get("planner") in ("备团用户", "主持人")
assert meta.get("status") in ("进行中", "已结束", "搁置", "草案")
print(f"Arc perfect-pizza-arc: name={meta.get('name')}, level={meta.get('level')}, planner={meta.get('planner')}, status={meta.get('status')}")

# State record
sr = store.read("state-records", "2026-07-24-林默结识老郑茶水间的忘年交")
assert sr is not None
meta, _ = sr
assert meta.get("title") == "林默结识老郑——茶水间的忘年交"
assert meta.get("type") == "关系变化"
assert meta.get("date") == "2026-07-24"
print(f"State record: title={meta.get('title')}, type={meta.get('type')}, date={meta.get('date')}")

# list_docs
chars = store.list_docs("characters")
print(f"list_docs(characters): {len(chars)} entries")
arcs = store.list_docs("story-arcs")
print(f"list_docs(story-arcs): {len(arcs)} entries")

# balance_report works with English keys (via _normalize_level)
bp = balance_report(store)
print(f"balance_report: {bp}")

# Test _normalize_level with English keys (translated by _parse_doc)
# Old Chinese keys also work because _parse_doc auto-translates them
for label, yaml_str in [("CN→EN", "---\n级别: 主要\n---\n\nx"), ("EN", "---\nlevel: 单局\n---\n\nx"), ("EN2", "---\nlevel: 次要局部\n---\n\nx")]:
    meta, _ = _parse_doc(yaml_str)
    assert "level" in meta, f"{label}: expected 'level' key in translated meta"
    print(f"_normalize_level({label}): {_normalize_level(meta)} (raw={meta.get('level')})")

# Both CN and EN keys produce valid results
cn_parsed, _ = _parse_doc("---\n级别: 主要\n---\n\nx")
cn_parsed2, _ = _parse_doc("---\n级别: 主要\n---\n\nx")
en_parsed, _ = _parse_doc("---\nlevel: 主要\n---\n\nx")
assert _normalize_level(cn_parsed) == _normalize_level(en_parsed), "CN and EN keys should produce same result"
print("_normalize_level compatibility: PASS (CN and EN keys produce same result)")

# Test round-trip: old Chinese file → parse → dump → re-parse
old_yaml = "---\n名称: 测试场景\n地点: test-loc\n在场者: [player1, player2]\n---\n\nbody"
meta, body = _parse_doc(old_yaml)
assert meta == {"name": "测试场景", "location": "test-loc", "attendees": ["player1", "player2"]}
new_doc = _dump_doc(meta, body)
meta2, body2 = _parse_doc(new_doc)
assert meta2 == meta
print("Round-trip (CN → EN → CN): PASS")

print()
print("=== ALL VALIDATIONS PASSED ===")
