# AI 辅助编辑工具设计

> 版本: 1.0 | 日期: 2026-07-29 | 状态: 设计提案

---

## 一、问题分析

### 1.1 当前编辑器的问题

经过对 `core/tools.py`、`server/routes/editor.py`、`core/store.py`、`web_frontend/` 的全面调研，当前的 AI 辅助编辑器存在以下结构性问题：

| 问题 | 现状 | 影响 |
|------|------|------|
| **纯文本对话模式** | 编辑器 LLM 通过 chat 生成 YAML+Markdown 文本，API 解析后落盘 | AI 无法做精细编辑，只能全文重新生成 |
| **无解析输出** | `read_doc` 以 JSON `{meta, body}` 返回，但编辑器 chat 里 LLM 看不到结构化数据 | AI 需自己解析 YAML front matter |
| **无增量编辑** | 只有 `POST /api/data/{kind}/{slug}` 全量写 | 改一个字段也得重写整个文件 |
| **无 front matter 规范化** | 情景文件 front matter 为 `{}`；不同文件字段完整度差异巨大 | 跨文件查询不可靠，结构化检索受限 |
| **无校验层** | 无从检查必填字段、枚举值范围、字段类型 | 落盘文件可能格式不合法 |
| **模板与实现脱节** | `templates/*.md` 定义丰富字段，但 `tools.py` 生成的只有 4-6 个字段 | 前端编辑 UI 只显示少量字段 |
| **编辑器与 GM 工具分裂** | GM 用 function-calling 工具，编辑器用纯 chat | 两套模式无法共享能力 |

### 1.2 核心矛盾

```
编辑器 LLM 想做的事情：         实际能做到的事情：
"把林默的装备加上收容手提箱"  →  读出整篇 → 理解整篇 → 修改 → 写回整篇
"把所有情景的 nature 规范化" →  做不到（无批量操作能力）
"检查所有文件是否合规"       →  做不到（无校验工具）
```

**根因**：编辑器缺少两样东西：
1. **高效编辑工具** — 让 AI 以最小 token 消耗完成精确编辑
2. **规范化工具** — 让 AI 能批量校验和修复 front matter

---

## 二、设计目标

### 2.1 核心理念

> **从"chat about files"升级为"operate on files"**

编辑工具 = **文件系统操作 + 结构化解析 + 校验反馈**，封装为 LLM 可调用的 function-calling 工具。

### 2.2 设计原则

1. **Surgical（精准）**：每个工具做一件事，最小化 token 消耗
2. **Structured（结构化）**：输入/输出都是解析后的数据，AI 不需要手写 YAML
3. **Validating（校验）**：写操作自动附带校验反馈
4. **Composable（可组合）**：原子工具可被 AI 编排为复杂工作流
5. **Consistent（一致）**：复用 `core/tools.py` 的 `@tool` 注册模式

### 2.3 与 GM 工具的定位差异

| | GM 工具 (tools.py) | 编辑工具 (editor_tools.py) |
|---|---|---|
| **使用场景** | 游戏运行时，AI 主持人裁决+创作 | 备团阶段，AI 编辑助手规划+整理 |
| **操作粒度** | 创建为主（draft/finalize/create） | 读写改删全生命周期 |
| **校验强度** | 轻量（弧光级别检查） | 完整（schema 校验 + 引用完整性） |
| **批量能力** | 无 | validate_all / normalize_all |
| **输出对象** | 玩家可见的文本 | 备团用户可见的编辑结果 |

### 2.4 编码约束（硬性要求）

**所有文件 I/O 操作必须显式指定 `encoding="utf-8"`**，不允许依赖系统默认编码。

#### 适用范围

涉及文件读写的所有代码路径：

| 层 | 文件 | 涉及操作 |
|---|------|---------|
| store.py | 已有的 `read_text`/`write_text`/`json.loads` | ✅ 已全部使用 `encoding="utf-8"` |
| editor.py | 已有的 `read_text`/`write_text` | ✅ 已全部使用 `encoding="utf-8"` |
| **editor_tools.py（新建）** | 通过 store.py 读写 | 间接依赖 store.py → ✅ |
| **schemas.py（新建）** | 不涉及文件 I/O | N/A |
| **schema_validator.py（新建）** | 不涉及文件 I/O | N/A |
| **schema_normalizer.py（新建）** | 不涉及文件 I/O | N/A |

#### 实现约束

```python
# ✅ 正确
path.read_text(encoding="utf-8")
path.write_text(content, encoding="utf-8")
json.loads(path.read_text(encoding="utf-8"))
json.dumps(obj, ensure_ascii=False)  # JSON 序列化也保持 Unicode

# ❌ 禁止
path.read_text()          # 依赖系统 locale，Windows 可能用 GBK
open(path, "w").write()   # 同上
open(path, "w", encoding="utf-8").write()  # 直接 open 也行，但优先用 pathlib
```

#### 新增 store.py 方法的编码检查清单

当 `store.py` 需要新增方法（如 `delete()`、`rename()`、跨文件引用扫描）时，每个包含文件读写的代码路径必须：

1. **读**：`path.read_text(encoding="utf-8")` 或 `json.loads(path.read_text(encoding="utf-8"))`
2. **写**：`path.write_text(content, encoding="utf-8")` 或 `path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")`
3. **YAML**：`yaml.safe_load(text)` 和 `yaml.dump(data, allow_unicode=True)` — PyYAML 默认 `allow_unicode=True`

#### 背景

ATRPG 的所有数据文件包含中文 front matter 和中文 Markdown 正文。Windows 系统的默认编码（locale）可能是 GBK/CP936，不指定 `encoding="utf-8"` 会导致：
- 中文字符写入时被错误编码
- 跨平台（Windows/Linux/macOS）迁移时乱码
- JSON/YAML 序列化时 Unicode 转义（`\uXXXX`）导致可读性下降

当前 `store.py` 有 18 处文件 I/O 调用，已 100% 使用 `encoding="utf-8"`。新建代码必须保持此标准。

---

## 三、工具目录

### A 类：核心编辑工具（效率优先）

#### `read_doc` — 读取文档

**目标**：让 AI 以结构化形式读取一个文件，同时获得关联上下文。

```
输入:
  kind:    文档类型 (characters|npcs|scenes|locations|items|story-arcs|state-records|terminology)
  slug:    文档 slug
  include_related: bool (默认 false，是否附带关联文件摘要)

返回:
  {
    path: "...",
    meta: { name:"林默", type:"玩家角色", current_scene:"back-alley", ... },
    body: "# 林默\n\n## 基础信息\n...",
    related: {                           # 仅 include_related=true 时
      scenes: [{slug, name}],            # 角色：所在情景
      arcs: [{slug, name, level}],       # 角色/NPC：关联弧光
      npcs: [{slug, name}],              # 情景：在场 NPC
    },
    issues: [{field, severity, message}]  # 自动附带校验结果
  }
```

**关键设计**：返回的不是原始 YAML 文本，而是解析后的 `meta` 字典 + `body` 字符串 + 可选关联上下文。`issues` 字段自动提供校验反馈，AI 不需要再次调用 validate。

---

#### `write_doc` — 写入/覆盖文档

**目标**：创建新文档或全量替换已有文档。

```
输入:
  kind:    文档类型
  slug:    文档 slug（新建时可选，不填则由系统从 meta.name 生成）
  meta:    { name, type, identity, nature, ... }
  body:    Markdown 正文
  overwrite: bool (默认 true，设为 false 则 slug 已存在时报错)

返回:
  {
    ok: true,
    path: "...",
    slug: "...",
    issues: [...]  # 自动校验反馈（warnings 不阻止写入）
  }
```

**关键设计**：与 GM 的 `create_npc` 等不同，`write_doc` 是通用工具——不限定字段，AI 可自由构造 meta。`issues` 提供即时的规范化反馈。

**slug 规则**：slug 来自文件名（新建时由 `slugify(meta.name)` 生成），不在 front matter 中存储。AI 传入的 `meta` 中即使包含 `slug` 也会被忽略（防止双重真相源）。

---

#### `patch_meta` — 修改 Front Matter

**目标**：在不触及 body 的情况下，增/改/删 front matter 字段。**这是利用率最高的工具**——改一个字段不应该重写整个文件。

```
输入:
  kind:    文档类型
  slug:    文档 slug
  set:     要设置/更新的字段 { field: value, ... }     # merge 模式
  delete:  要删除的字段列表 ["field1", "field2"]       # 可选

返回:
  {
    ok: true,
    changes: [
      { field: "status", old: "草案", new: "正式", action: "set" },
      { field: "deprecated_field", old: "xxx", new: null, action: "delete" },
    ],
    meta: { ... },   # 修改后的完整 meta
    issues: [...]    # 校验反馈
  }
```

**使用场景**：
- "把所有 NPC 的 nature 统一为「支撑剧情」"
- "把林默的 current_scene 改为 perfect-corner-kitchen"
- "给完美披萨弧光补上 current_stage: 新的稳定"

**关键设计**：不是全量替换 meta——是 **merge patch**。AI 只传要改的字段，其余保持不变。`set` 和 `delete` 分开操作，语义清晰。

**系统字段保护**：尝试 set/delete `slug` 或 `updated` 会报错：
- `slug` → `"slug 是文件名，请用 rename_doc 重命名"`
- `updated` → `"updated 由系统自动维护，不可手动修改"`

---

#### `patch_body` — 修改 Markdown 正文

**目标**：在 body 中做精确的增/删/改，不使用整体替换。

```
输入:
  kind:      文档类型
  slug:      文档 slug
  operation: "insert_after" | "insert_before" | "replace" | "append" | "delete"
  target:    目标定位（见下文）
  content:   要插入/替换的内容（insert/replace 时必填）

target 的三种定位方式:
  1. 标题定位: { heading: "## 基础信息" }
     → 在「## 基础信息」的下一个同级标题之前操作
  2. 行号定位: { line_start: 42, line_end: 55 }
     → 精确行号范围
  3. 锚文本定位: { anchor: "性格：寡言", context_lines: 2 }
     → 搜索匹配行，操作前/后

返回:
  {
    ok: true,
    operation: "insert_after",
    target_summary: "在 ## 剧情连接 之后插入",
    preview: "..."  # 受影响区域的前后文（最多 200 字）
  }
```

**使用场景**：
- "在 ## 基础信息 之后插入「- 别名：小林」"
- "把 ## 能力与资源 整节替换为新的技能列表"
- "在 body 末尾追加一段新剧情"

**关键设计**：标题定位为主要方式（因为 Markdown 文档天然以标题为组织单元）。行号定位作为精确后备。AI 不需要数行号——它可以从 read_doc 输出中引用。

---

#### `search_docs` — 跨文档搜索

**目标**：按照内容或元数据条件查找文档。

```
输入:
  kind:       文档类型 或 "all"
  query:      文本搜索词（可选）
  meta_filter: { level: "主要", status: "进行中" }  # 元数据过滤（可选）
  limit:      最大返回数 (默认 20)

返回:
  {
    total: 5,
    results: [
      {
        kind: "story-arcs", slug: "perfect-pizza-arc",
        name: "完美披萨", meta_summary: "级别:单局 阶段:高潮",
        snippet: "...一股异常的橙光从门缝下渗出..."
      },
      ...
    ]
  }
```

**使用场景**：
- "找到所有进行中的主要弧光"
- "搜索所有提到「橙光」的文件"
- "列出所有 nature 为空的 NPC"

---

### B 类：Front Matter 规范化工具

#### `validate_doc` — 单文件校验

**目标**：按类型 schema 检查一个文件，返回问题列表。

```
输入:
  kind: 文档类型
  slug: 文档 slug

返回:
  {
    valid: false,
    errors: [                         # 阻断性问题
      { field: "location", severity: "error", message: "情景缺少必填字段 location" },
    ],
    warnings: [                       # 建议性问题
      { field: "nature", severity: "warning", message: "nature 值不在枚举中：当前为空，允许值：主线/临时生成/可回收" },
    ],
    summary: {
      required_ok: 4, required_missing: 1,
      enum_ok: 2, enum_invalid: 1,
      type_ok: 3, type_mismatch: 0,
    }
  }
```

**Schema 规则**（详见第四部分）：
- **required**：必填字段检查
- **enum**：枚举值范围检查
- **type**：字段类型检查（string/number/list）
- **cross_ref**：跨文件引用完整性（如场景的 location 字段指向的地点是否存在）

---

#### `normalize_doc` — 单文件自动修复

**目标**：自动修复可修复的问题，返回修改清单。

```
输入:
  kind:    文档类型
  slug:    文档 slug
  options:
    fill_defaults:   bool  # 为缺失字段填入默认值
    fix_enums:        bool  # 修正枚举值格式（如 "main" → "主要"）
    extract_from_body: bool # 从正文提取信息补全 meta（如从 body 提取 nature）
    dry_run:          bool  # 仅报告不修改

返回:
  {
    dry_run: false,
    changes: [
      { field: "nature", old: "", new: "支撑剧情 / 可回收", source: "default" },
      { field: "current_stage", old: "climax", new: "高潮", source: "enum_fix" },
      { field: "location", old: "", new: "perfect-corner-pizza", source: "body_extract" },
    ],
    meta: { ... },    # 修改后的完整 meta
    remaining_issues: [...]  # 无法自动修复的问题
  }
```

**自动修复策略**：
| 修复类型 | 策略 |
|---------|------|
| 缺失必填字段 | 从类型的 `defaults` 表填入（见 schema） |
| 枚举值格式不对 | fuzzy match + 手动映射表修正 |
| 字段可从 body 提取 | 用规则从 body 中推断（见下文） |
| 字段类型错误 | 尝试类型转换，失败则保留原值并标记 warning |

**Body → Meta 提取规则**（`extract_from_body` 开启时）：
| 类型 | 提取逻辑 |
|------|---------|
| 情景 | 从「## Front matter」段落提取 name/nature/location/time |
| 弧光 | 从「## 概览」列表提取 level/planner/current_stage/status/hook |
| 角色 | 从「## 基础信息」列表提取 identity/appearance/age |
| NPC | 从「## 基础信息」列表提取 identity/nature |

---

#### `validate_all` — 批量校验

**目标**：对整个游戏目录生成校验报告。

```
输入:
  kind: 文档类型（可选，不填则校验所有类型）

返回:
  {
    checked_at: "2026-07-29 16:30",
    summary: {
      total_files: 45,
      valid: 12,
      with_errors: 8,
      with_warnings: 25,
      by_kind: {
        "story-arcs": { total: 3, valid: 2, errors: 1, warnings: 0 },
        "scenes":      { total: 7, valid: 0, errors: 7, warnings: 7 },
        ...
      }
    },
    details: [
      { kind: "scenes", slug: "perfect-corner-pizza",
        errors: [{ field: "location", message: "..." }],
        warnings: [{ field: "nature", message: "..." }] },
      ...
    ]
  }
```

---

#### `normalize_all` — 批量自动修复

**目标**：批量规范化，可 dry-run 预览。

```
输入:
  kind:    文档类型（可选）
  options: 同 normalize_doc
  dry_run: bool (默认 true，安全第一)

返回:
  (dry_run=true)  { summary: { would_fix: 42, issues_remain: 18 }, preview: [...] }
  (dry_run=false) { summary: { fixed: 42, skipped: 5, issues_remain: 18 }, changes: [...] }
```

---

### C 类：辅助工具

#### `list_docs` — 增强列表

比现有 `store.list_docs()` 多返回摘要和关键字段。

```
输入:
  kind:    文档类型
  sort_by: "name" | "updated" | "slug" (默认 name)
  limit:   最大返回数 (默认 50)
  offset:  分页偏移

返回:
  {
    total: 45,
    items: [
      {
        slug: "perfect-pizza-arc", name: "完美披萨",
        meta_highlights: { level: "单局", current_stage: "高潮", status: "进行中" },
        updated: "2026-07-24 23:07",
        issues_count: 2
      },
      ...
    ]
  }
```

---

#### `delete_doc` — 删除文档

```
输入:
  kind: 文档类型
  slug: 文档 slug
  force: bool (默认 false，有引用时需 force=true)

返回:
  { ok: true, deleted: "data/scenes/old-scene.md", warnings: ["被 2 个弧光引用"] }
```

---

#### `rename_doc` — 重命名文档

```
输入:
  kind:     文档类型
  old_slug: 当前 slug
  new_slug: 新 slug

返回:
  { ok: true, old_path: "...", new_path: "...", references_updated: 3 }
```

**关键行为**：重命名文件即改变 slug。自动扫描所有其他文档的 body 中引用旧 slug 的地方，更新为新 slug。不需要修改任何 front matter（因为 slug 不在 front matter 中）。

---

## 四、关键数据结构：slug 的真相源

### 4.0 slug = 文件名（唯一真相源）

**slug 就是文件名去掉 `.md` 后缀。它不是 front matter 字段。**

当前 `store.py` 的行为是矛盾的：
```python
# store.py:392 — write() 时把 slug 写入 front matter
meta.setdefault("slug", slug)

# store.py:417 — list_docs() 时用的是文件名
out.append({"slug": p.stem, "meta": meta})
```

这产生了**两个 slug**：文件名里的和 front matter 里的。它们可能不一致（重命名文件但没改 front matter、或 `patch_meta` 改了 front matter slug 但没重命名文件）。

**设计方案**：

1. **`store.write()` 不再写入 `slug` 到 front matter**。删除 `meta.setdefault("slug", slug)`。
2. **`store._dump_doc()` 确保 `slug` 和 `updated` 不出现在输出中**（`updated` 同理——它是系统维护的，不应存到文件里？实际上 `updated` 存进去有助于人工查看文件最后修改时间，但 `slug` 没有任何附加价值）。
3. **`patch_meta` 拒绝操作系统字段**：尝试 set/delete `slug` 或 `updated` 时直接报错。
4. **所有读取 slug 的代码统一从文件名推导**：`Path(filepath).stem`。
5. **已存在的文件中的 `slug` front matter 字段**：读取时忽略（`_parse_doc` 已通过 `_FIELD_MAP` 不映射它），写入时不再产生，`normalize_doc` 可选清理旧字段。

**映射关系**：

| 概念 | 存储位置 | 示例 |
|------|---------|------|
| slug | **文件名** (不含 `.md`) | `data/characters/林默.md` → slug=`林默` |
| name | front matter `name:` | 显示名称，可以和 slug 不同 |
| path | 文件系统完整路径 | `H:\gitrepo\atrpg\test_session\...\data\characters\林默.md` |

**对工具的影响**：

| 工具 | slug 行为 |
|------|----------|
| `read_doc` | slug 从文件名推导，不读 front matter 中的 slug |
| `write_doc` | slug 来自文件名（新建时由 `slugify(name)` 生成） |
| `patch_meta` | **禁止**修改 slug（报错："slug 由文件名决定，请用 rename_doc"） |
| `rename_doc` | 重命名文件，自动清理旧文件中残留的 front matter slug |
| `normalize_doc` | 可选删除 front matter 中的冗余 slug 字段 |
| `validate_doc` | 不检查 slug 字段（它是文件名，不属于 front matter schema） |

---

## 五、Schema 系统设计

### 5.1 Schema 定义格式

每种文档类型定义一个 schema，存储在 `core/schemas.py`：

```python
# core/schemas.py

SCHEMAS: dict[str, dict] = {}

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
        "current_scene":   {"type": "str"},
        "current_status":  {"type": "str"},
    },
    # 注意：slug/updated 不在 fields 中——它们是系统字段，由文件名和文件时间戳管理
    "defaults": {
        "type": "玩家角色",
        "status": "待确认",
    },
    "body_sections": ["基础信息", "性格与背景", "能力与资源", "剧情连接"],
}

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
        "current_scene":   {"type": "str"},
    },
    "defaults": {
        "type": "NPC",
        "nature": "支撑剧情",
    },
    "body_sections": ["基础信息", "性格与背景", "与其他角色关系", "所知信息"],
}

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

SCHEMAS["scenes"] = {
    "required": ["name", "nature", "location"],
    "fields": {
        "name":     {"type": "str"},
        "nature":   {"type": "enum", "values": ["主线", "临时生成", "可回收"]},
        "location": {"type": "str"},
        "time":     {"type": "str"},
        "attendees":{"type": "list", "item_type": "str"},
    },
    "defaults": {
        "nature": "可回收",
    },
    "body_sections": ["在场角色", "背景", "事件推进", "镜头结束状态"],
    "cross_refs": {
        "location": "locations",   # location 字段的值必须是存在的 locations slug
    },
}

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
```
### 5.2 系统字段（不在 front matter 中存储）

所有文档类型共享两个系统字段，它们**不在 schema 的 `fields` 中定义，也不应出现在 front matter 中**：

| 字段 | 来源 | 说明 |
|------|------|------|
| `slug` | **文件名**（去掉 `.md`） | 文档唯一标识，由 `slugify(name)` 生成。只通过重命名文件来改变 |
| `updated` | `store.write()` 自动设置 | 最后修改时间 `"%Y-%m-%d %H:%M"`，写入文件但不在 schema 中校验 |

**`patch_meta` 的行为**：
- 尝试 set/delete `slug` → 报错 `"slug 是文件名，请用 rename_doc 重命名"`
- 尝试 set/delete `updated` → 报错 `"updated 由系统自动维护，不可手动修改"`

**`normalize_doc` 的行为**：
- 检测到 front matter 中有 `slug` 字段 → 视为冗余，自动删除
- 检测到 front matter 中有 `updated` 字段 → 保留（方便人工查看），但如果有多个不规范的 `updated` 格式则统一

**校验引擎中的处理**：
- `validate()` 不检查 `slug`/`updated`——它们不在 `fields` 中，自动跳过
- 如果 meta 中出现 `slug`/`updated`，校验引擎产生一个 **info** 级别的提示（不是 error/warning）

### 5.3 校验引擎

```python
# core/schema_validator.py

def validate(meta: dict, kind: str, store=None) -> ValidationResult:
    """对一份 meta 执行完整校验。store 可选，提供时执行 cross_ref 检查。"""
    schema = SCHEMAS.get(kind)
    if not schema:
        return ValidationResult(valid=True, errors=[], warnings=[])

    errors = []
    warnings = []

    # 1. 必填字段检查
    for field in schema["required"]:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(ValidationIssue(field, "error", f"缺少必填字段 {field}"))

    # 2. 字段规范检查
    for field, spec in schema.get("fields", {}).items():
        val = meta.get(field)
        if val is None:
            continue

        if spec["type"] == "enum":
            if val not in spec["values"]:
                warnings.append(ValidationIssue(
                    field, "warning",
                    f"字段 {field} 的值 '{val}' 不在枚举范围内：{spec['values']}"
                ))

        elif spec["type"] == "int":
            if not isinstance(val, int):
                warnings.append(ValidationIssue(field, "warning", f"字段 {field} 应为整数，当前为 {type(val).__name__}"))
            elif "range" in spec:
                lo, hi = spec["range"]
                if not (lo <= val <= hi):
                    warnings.append(ValidationIssue(field, "warning", f"字段 {field} 值 {val} 超出范围 [{lo}, {hi}]"))

        elif spec["type"] == "list":
            if not isinstance(val, list):
                warnings.append(ValidationIssue(field, "warning", f"字段 {field} 应为列表"))

    # 3. 跨文件引用检查
    if store and "cross_refs" in schema:
        for field, ref_kind in schema["cross_refs"].items():
            val = meta.get(field)
            if val and isinstance(val, str):
                if store.read(ref_kind, val) is None:
                    warnings.append(ValidationIssue(
                        field, "warning",
                        f"字段 {field} 引用的 {ref_kind}/{val} 不存在"
                    ))

    # 4. 未知字段检查
    known_fields = set(schema.get("fields", {}).keys()) | {"slug", "updated"}
    for key in meta:
        if key not in known_fields and not key.startswith("_"):
            warnings.append(ValidationIssue(key, "warning", f"未知字段 {key}（不在 {kind} schema 中）"))

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)
```

### 5.4 自动修复引擎

```python
# core/schema_normalizer.py

def normalize(meta: dict, body: str, kind: str, options: NormalizeOptions) -> NormalizeResult:
    """根据 schema 自动修复 meta。"""
    schema = SCHEMAS.get(kind, {})
    changes = []

    # 1. 填入默认值
    if options.fill_defaults:
        for field, default_val in schema.get("defaults", {}).items():
            current = meta.get(field)
            if current is None or (isinstance(current, str) and not current.strip()):
                meta[field] = default_val
                changes.append(Change(field, current, default_val, "default"))

    # 2. 枚举值修正
    if options.fix_enums:
        for field, spec in schema.get("fields", {}).items():
            if spec["type"] != "enum":
                continue
            val = meta.get(field)
            if val is None:
                continue
            if val not in spec["values"]:
                fixed = _fuzzy_match_enum(val, spec["values"])
                if fixed:
                    meta[field] = fixed
                    changes.append(Change(field, val, fixed, "enum_fix"))

    # 3. 从 body 提取信息
    if options.extract_from_body:
        extracted = _extract_from_body(body, kind, schema)
        for field, value in extracted.items():
            current = meta.get(field)
            if current is None or (isinstance(current, str) and not current.strip()):
                meta[field] = value
                changes.append(Change(field, current, value, "body_extract"))

    return NormalizeResult(meta=meta, changes=changes)
```

---

## 六、架构集成

### 6.1 文件结构

```
core/
├── tools.py              # [现有] GM 工具（不改动）
├── editor_tools.py       # [新建] 编辑工具定义 + 执行
├── schemas.py            # [新建] 文档类型 schema 定义
├── schema_validator.py   # [新建] 校验引擎
├── schema_normalizer.py  # [新建] 自动修复引擎
├── store.py              # [现有] 文件 I/O（可能需要新增方法）
└── editor_runtime.md     # [修改] 更新系统提示词，注入工具使用说明

server/routes/
└── editor.py             # [修改] 编辑器 chat 改为 tool-calling 模式
```

### 6.2 工具注册模式

复用 `core/tools.py` 的 `@tool` 装饰器模式，在 `core/editor_tools.py` 中定义：

```python
# core/editor_tools.py

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from . import store, schemas, schema_validator, schema_normalizer

_REGISTRY: dict[str, EditorToolDef] = {}

@dataclass
class EditorToolDef:
    schema: dict[str, Any]
    func: Callable[..., Awaitable[str]]

def editor_tool(name: str, description: str, params: dict[str, Any]):
    """注册编辑器工具。"""
    def deco(func):
        _REGISTRY[name] = EditorToolDef(
            schema={
                "type": "function",
                "function": {"name": name, "description": description, "parameters": params}
            },
            func=func
        )
        return func
    return deco

def editor_tool_schemas() -> list[dict[str, Any]]:
    return [td.schema for td in _REGISTRY.values()]

async def dispatch(ctx: EditorContext, call) -> str:
    td = _REGISTRY.get(call.name)
    if td is None:
        return f"错误：未知编辑器工具 '{call.name}'"
    return await td.func(ctx, **call.arguments)
```

### 6.3 编辑器 chat 改造

当前编辑器 chat（`POST /api/editor/chat`）是纯文本对话。改造为 tool-calling 模式：

```python
# server/routes/editor.py 中的改造

@router.post("/chat")
async def editor_chat(body: dict[str, Any]):
    message = body.get("message", "").strip()
    # ... 加载上下文 ...

    llm_messages = [
        {"role": "system", "content": system_content_with_tool_instructions},
    ] + history[-30:] + [
        {"role": "user", "content": message}
    ]

    # 改为 tool-calling 模式
    resp = await client().chat.completions.create(
        model=c.model,
        messages=llm_messages,
        temperature=0.8,
        tools=editor_tool_schemas(),      # 注入编辑工具
        tool_choice="auto",
    )

    # 处理 tool calls 循环
    while resp.choices[0].message.tool_calls:
        for tc in resp.choices[0].message.tool_calls:
            result = await dispatch(editor_ctx, tc)
            llm_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        resp = await client().chat.completions.create(...)

    reply = resp.choices[0].message.content or ""
    # ... 保存历史 ...
```

### 6.4 系统提示词更新

`core/editor_runtime.md` 需要新增工具使用说明：

```markdown
## 编辑工具（新增）

你现在可以调用以下工具来操作游戏文件，而不只是生成文本：

### 核心编辑
- `read_doc` — 读取文件（含解析后的 meta 和关联上下文）
- `write_doc` — 创建/覆盖文件
- `patch_meta` — 修改 front matter 字段（推荐：改一个字段时用此工具，而非重写整个文件）
- `patch_body` — 在 Markdown 正文中精确插入/替换/删除内容
- `search_docs` — 跨文件搜索

### Front Matter 规范化
- `validate_doc` — 校验单个文件的 front matter
- `normalize_doc` — 自动修复 front matter 问题
- `validate_all` — 批量校验，生成报告
- `normalize_all` — 批量自动修复（请先 dry_run 预览）

### 辅助
- `list_docs` — 列出文件（含关键字段摘要）
- `delete_doc` — 删除文件
- `rename_doc` — 重命名文件（自动更新引用）

## 工具使用原则

1. **优先使用精确工具**：改一个字段用 `patch_meta`，不要 `write_doc` 重写全文
2. **写入前先读取**：修改文件前先 `read_doc` 了解当前内容
3. **批量操作先预览**：`normalize_all` 先用 `dry_run=true`
4. **创建新文件用 `write_doc`**：告诉 AI 完整的 meta 和 body
5. **校验反馈已自动提供**：每次 read_doc/write_doc/patch_meta 返回时已自动包含 issues
```

---

## 七、工具使用场景示例

### 场景 1：规范化一个情景文件

```
用户: "把 perfect-corner-pizza 情景的 front matter 规范化"

AI 内部工具调用序列:
  1. read_doc(kind="scenes", slug="perfect-corner-pizza")
     → 返回: meta={}, body="...## Front matter\n- name: ...## 在场..."
     → issues: [{field:"name", severity:"error", message:"缺少必填字段 name"},
                 {field:"nature", severity:"error", message:"缺少必填字段 nature"},
                 {field:"location", severity:"error", message:"缺少必填字段 location"}]

  2. normalize_doc(kind="scenes", slug="perfect-corner-pizza",
                   options={fill_defaults:true, extract_from_body:true, dry_run:false})
     → 返回: {
         changes: [
           {field:"name", old:"", new:"完美一角披萨店后巷", source:"body_extract"},
           {field:"nature", old:"", new:"可回收", source:"default"},
           {field:"location", old:"", new:"perfect-corner-pizza", source:"body_extract"},
         ],
         remaining_issues: []
       }

AI 回复:
  "已规范化 perfect-corner-pizza 的 front matter：
   - name → 「完美一角披萨店后巷」（从正文提取）
   - nature → 「可回收」（默认值）
   - location → 「perfect-corner-pizza」（从正文提取）
   所有必填字段已补全，无遗留问题。"
```

### 场景 2：批量修改 NPC 的 nature 字段

```
用户: "把所有 NPC 的 nature 都改成「支撑剧情」"

AI 内部工具调用序列:
  1. search_docs(kind="npcs", meta_filter={})
     → 返回: 6 个 NPC 列表

  2. patch_meta(kind="npcs", slug="lao-zheng", set={nature:"支撑剧情"})
  3. patch_meta(kind="npcs", slug="gm-zhao", set={nature:"支撑剧情"})
  4. patch_meta(kind="npcs", slug="la-massa", set={nature:"支撑剧情"})
  ... (每个 NPC 一次 patch_meta 调用)

AI 回复:
  "已更新 6 个 NPC 的 nature 为「支撑剧情」。"
```

### 场景 3：为弧光补充关系信息

```
用户: "在完美披萨弧光的 ## 关联要素 章节里补上 location: perfect-corner-pizza"

AI 内部工具调用序列:
  1. read_doc(kind="story-arcs", slug="perfect-pizza-arc")
     → 返回 body 中有 ## 关联要素，需要补充 location

  2. patch_body(kind="story-arcs", slug="perfect-pizza-arc",
                operation="insert_before",
                target={heading:"## 状态变化记录"},
                content="- **地点**：perfect-corner-pizza（完美一角披萨店）\n")

AI 回复:
  "已在完美披萨弧光的「关联要素」中补充地点引用。"
```

### 场景 4：全局规范化检查

```
用户: "检查一下所有文件有没有问题"

AI 内部工具调用序列:
  1. validate_all()
     → 返回: {
         summary: { total_files:45, valid:12, with_errors:8, with_warnings:25 },
         details: [
           {kind:"scenes", slug:"perfect-corner-pizza",
            errors:[{field:"location", message:"..."}]},
           ...
         ]
       }

AI 回复:
  "校验报告：45 个文件中，12 个通过，8 个有错误，25 个有警告。

   错误（需修复）：
   - 7 个情景文件缺少 location 字段
   - 1 个弧光缺少 name 字段

   警告（建议修复）：
   - 15 个文件有不在 schema 中的未知字段
   - 3 个 NPC 的 nature 值不在枚举范围内
   - 2 个情景引用的 location slug 不存在

   要我帮你自动修复吗？建议先用 normalize_all(dry_run=true) 预览。"
```

---

## 八、实施计划

### 阶段 0：slug 真相源重构（全线，0.5-1 天）🔴 P0 前置

**目标**：消除 `slug` 作为 front matter 字段的双重真相源。对 AI 接口保持不变（参数仍叫 `slug`），内部统一从文件名推导。

**影响范围**（基于全代码库审计）：

| 文件 | 行号 | 当前行为 | 修改 |
|------|------|---------|------|
| `core/store.py` | 392 | `meta.setdefault("slug", slug)` 写入 front matter | **删除此行**，`write()` 不再把 slug 写进 meta |
| `core/tools.py` | 133 | `draft_character` 的 meta 含 `"slug": slug` | **删除** meta dict 中的 `"slug"` 键 |
| `core/tools.py` | 245 | `create_npc` 的 meta 含 `"slug": slug` | **删除** |
| `core/tools.py` | 263 | `create_item` 的 meta 含 `"slug": slug` | **删除** |
| `core/tools.py` | 285 | `create_scene` 的 meta 含 `"slug": slug` | **删除** |
| `core/tools.py` | 303 | `create_location` 的 meta 含 `"slug": slug` | **删除** |
| `core/tools.py` | 341 | `record_state` 的 meta 含 `"slug": name` | **删除** |
| `core/arc.py` | 126 | `plan_arc` 的 meta 含 `"slug": slug` | **删除** |

**无需修改**（已正确使用文件名来源的 slug）：

| 文件 | 说明 |
|------|------|
| `core/store.py:417` | `list_docs()` 返回的 `"slug"` 来自 `p.stem`（文件名），✅ 正确 |
| `core/tools.py:430,434,446,455` | `d["slug"]` 从 `list_docs` 获取，✅ 正确 |
| `core/store.py:702,705,728,732` | `d["slug"]` 从 `list_docs` 获取，✅ 正确 |
| `server/routes/editor.py:131` | `meta.pop("slug", None)` 已经主动清理，✅ 不受影响 |
| `core/process_turn.py:183` | `return d["slug"]` 从 `list_docs` 获取，✅ 正确 |

**AI 接口不变**：所有工具的 `slug` 参数名保持不变（`char_slug`、`scene_slug`、`arc_slug` 等），LLM 仍然通过 slug 值引用文件。内部实现改为 `store.read(kind, slug)` → `Path(self.root / "data" / kind / f"{slug}.md")`，等价。

**向后兼容**：已落盘的旧文件 front matter 中残留的 `slug:` 行，`_parse_doc` 读取时自然忽略（无对应 `_FIELD_MAP` 映射），`normalize_doc` 可选清理。

### 阶段 1：基础层（1-2 天）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `core/schemas.py` | 8 种文档类型 schema 定义 | P0 |
| `core/schema_validator.py` | 校验引擎（required/enum/type/cross_ref） | P0 |
| `core/schema_normalizer.py` | 自动修复引擎（defaults/enum_fix/body_extract） | P0 |

### 阶段 2：核心编辑工具（2-3 天）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `core/editor_tools.py` — `read_doc` | 结构化读取 + 自动校验反馈 | P0 |
| `core/editor_tools.py` — `write_doc` | 通用写入 + 自动校验反馈 | P0 |
| `core/editor_tools.py` — `patch_meta` | Front matter merge patch | P0 |
| `core/editor_tools.py` — `patch_body` | Markdown body 精确编辑 | P0 |
| `core/editor_tools.py` — `search_docs` | 跨文件搜索 | P1 |
| `store.py` 扩展 | `delete()`、`rename()` 方法 + 引用扫描 | P1 |

### 阶段 3：规范化工具（1-2 天）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `core/editor_tools.py` — `validate_doc` | 单文件校验工具 | P0 |
| `core/editor_tools.py` — `normalize_doc` | 单文件自动修复工具 | P0 |
| `core/editor_tools.py` — `validate_all` | 批量校验报告 | P1 |
| `core/editor_tools.py` — `normalize_all` | 批量自动修复 | P1 |

### 阶段 4：集成（1-2 天）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `server/routes/editor.py` 改造 | 编辑器 chat 改为 tool-calling 模式 | P0 |
| `core/editor_runtime.md` 更新 | 工具使用说明 + 工具选择指导 | P0 |
| `core/editor_tools.py` — `list_docs`/`delete_doc`/`rename_doc` | 辅助工具 | P1 |
| 联调测试 | 端到端验证 | P0 |

### 阶段 5：前端适配（后续）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 编辑器 UI 增加校验面板 | 显示文件 issues 状态 | P2 |
| 编辑器 UI 增加规范化按钮 | 一键规范化当前文件 | P2 |
| 编辑器 UI 增加批量操作入口 | 全局校验报告面板 | P2 |

---

## 九、设计决策记录

### 9.0 slug = 文件名，不在 front matter 中

**slug 的唯一真相源是文件名**。不在 front matter 中存储 slug。理由：
- 防止双重真相源（文件名的 slug 和 front matter 里的 slug 不一致）
- `patch_meta` 不能修改文件名（语义清晰：改 slug 用 `rename_doc`）
- 读取 slug 的代码全部统一为 `Path(filename).stem`
- `store.write()` 不再写入 `meta["slug"]`，已存在文件中的冗余 slug 被读取时忽略、规范化时清理

### 9.1 为什么用 function-calling 而不是纯 chat？

| 方案 | 优点 | 缺点 |
|------|------|------|
| **纯 chat**（现状） | 实现简单 | AI 无法精确编辑；需要手写 YAML；token 消耗大 |
| **function-calling**（推荐） | 精确操作；结构化输入；自动校验反馈 | 实现复杂度更高；需要工具调度逻辑 |
| **混合模式** | 灵活性最高 | 复杂度更高 |

选择 function-calling：编辑天然是操作序列，工具化是最自然的抽象。与 GM 工具的架构一致，降低认知负担。

### 9.2 `patch_meta` 用 merge 还是 replace？

选择 **merge**（只传要改的字段）。理由：
- AI 不需要知道全部字段（减少 token）
- 不会意外删除其他字段
- 配合 `delete` 参数处理字段删除

### 9.3 `patch_body` 用标题定位还是行号定位？

**标题定位为默认，行号定位作为后备**。理由：
- Markdown 文档以标题组织，标题定位最自然
- 行号定位在 AI 拿到 read_doc 的 body 后可行（AI 可以数行号）
- 锚文本定位处理"改某个具体文字"的场景

### 9.4 校验是同步还是异步？

**同步附带**。每次 `read_doc`/`write_doc`/`patch_meta` 返回时自动包含 `issues`。理由：
- AI 无需额外调用就能获得校验反馈
- 即时反馈帮助 AI 自我修正
- 不影响性能（校验是轻量操作）

### 9.5 `normalize_all` 默认 dry_run=true？

**是**。批量修改有风险，默认先预览。用户确认后再设 `dry_run=false` 执行。

---

## 十、风险与注意事项

1. **body → meta 提取的准确性**：从 Markdown 正文推断 front matter 字段是启发式的，可能有误提取。`extract_from_body` 应保守——只提取高度可信的匹配。

2. **Tool calling 循环深度**：大的批量操作可能产生大量 tool calls。需要设置最大循环次数（建议 20 轮），防止失控。

3. **文件锁冲突**：编辑工具和 GM 运行时可能同时操作同一文件。复用 `store.py` 的 `_LOCK` 机制。

4. **LLM 对工具的理解**：新增工具需要清晰的 description（含使用场景和示例），确保 LLM 在合适时机调用合适的工具。

5. **向后兼容**：`editor_tools.py` 与现有 `tools.py` 完全独立，不影响 GM 运行时。编辑器 chat 改造只影响 `POST /api/editor/chat`，不影响其他编辑器端点。

6. **UTF-8 编码一致性**：所有新建代码的文件 I/O 必须显式 `encoding="utf-8"`。新增 store.py 方法、JSON/YAML 序列化均为检查重点。每个 PR 需确认无遗漏的 `read_text()` / `write_text()` 裸调用。

---

## 十一、附录：工具一览

| # | 工具名 | 类型 | 描述 |
|---|--------|------|------|
| 1 | `read_doc` | 核心编辑 | 读取文档（结构化 meta + body + 关联上下文 + 校验反馈） |
| 2 | `write_doc` | 核心编辑 | 创建/覆盖文档 |
| 3 | `patch_meta` | 核心编辑 | 修改 front matter 字段（merge patch） |
| 4 | `patch_body` | 核心编辑 | 在 Markdown 正文中精确增/删/改 |
| 5 | `search_docs` | 核心编辑 | 跨文件搜索（文本 + 元数据过滤） |
| 6 | `validate_doc` | 规范化 | 按类型 schema 校验单文件 front matter |
| 7 | `normalize_doc` | 规范化 | 自动修复 front matter 问题 |
| 8 | `validate_all` | 规范化 | 批量校验，生成报告 |
| 9 | `normalize_all` | 规范化 | 批量自动修复（支持 dry_run） |
| 10 | `list_docs` | 辅助 | 列出文件（含关键字段摘要） |
| 11 | `delete_doc` | 辅助 | 删除文档 |
| 12 | `rename_doc` | 辅助 | 重命名文档（自动更新引用） |
