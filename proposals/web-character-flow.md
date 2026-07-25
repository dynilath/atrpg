# Web 角色创建与管理流程

## 背景

Web 端和 QQ Bot 端有本质差异：

| | QQ Bot | Web |
|---|---|---|
| 交互方式 | 群聊 @bot 自然语言 | 页面按钮 + 表单 + 对话框 |
| 角色创建 | 在聊天中描述 → AI 现场生成 | 独立入口"创建角色" → AI 生成 → 确认 |
| 角色绑定 | AI 工具调用自动绑定 | 用户手动选择 + 确认 |
| 信息呈现 | 仅文本 | 角色卡面板、场景面板 |

Web 端不应该照搬 Bot 的逻辑（让用户在聊天框里发"我想创建一个角色"）。

---

## 角色生命周期

```
  ┌──────────┐  点击"创建角色"  ┌──────────────┐  确认  ┌──────────┐
  │ 无角色    │ ─────────────→ │ 角色创建对话框 │ ─────→ │ 已绑定角色 │
  │          │                │ 描述→AI→预览   │       │          │
  └──────────┘                └──────────────┘       └──────────┘
        ↑                                                  │
        │             点击"选择已有角色"                      │
        │    ┌──────────────────┐                          │
        └─── │ 角色下拉 + 绑定按钮 │ ←───────────────────────┘
             └──────────────────┘      或"解除绑定"
```

---

## 玩家页面状态

### 状态 A：无绑定角色

侧边栏显示：

```
┌─ 角色 ─────────────────────────┐
│                                │
│    [ 创建角色 ]  (primary btn)  │
│                                │
│    ── 或选择已有角色 ──          │
│    [角色下拉 v] [绑定]          │
│                                │
└────────────────────────────────┘
```

聊天区正常可用（方便已绑定角色的其他玩家直接行动）。

### 状态 B：已绑定角色

侧边栏显示：

```
┌─ 角色 ─────────────────────────┐
│  林默                          │
│  身份：退役侦察兵                │
│  当前：码头仓库                  │
│  [解除绑定] (ghost btn)         │
└────────────────────────────────┘
```

---

## 角色创建对话框

### 触发

点击"创建角色"按钮。

### 流程

1. **输入阶段**：用户输入角色概念描述
   - 例如："一个退役的侦察兵，擅长潜行和观察，性格谨慎但讲义气"
2. **生成阶段**：调用 `POST /api/editor/characters`（type=pc）
   - 后端调用 LLM 生成完整角色卡
3. **预览阶段**：展示生成的角色
   - 姓名、身份、外貌、性格、能力标签
4. **确认**：用户点击"确认创建"
   - 写入 `data/characters/{slug}.md`
   - 调用 `PUT /api/users/{provider}/{id}/bind` 绑定
   - 关闭对话框，侧边栏刷新为"已绑定"

### 技术实现

- 复用 `POST /api/editor/characters` 接口（已有）
- 绑定复用 `PUT /api/users/{provider}/{id}/bind` 接口（已有）
- 组件：`CharacterCreateDialog`（新），在 PlayerPage 中以模态方式渲染

---

## 角色卡数据源

### 问题

当前 `CharacterCard` 从 `useGameStore.character` 读取角色信息，这个数据由 WebSocket 事件设置（GM bot 推送）。但 Web 端绑定角色走 REST API，不会触发 WebSocket 事件。

### 方案

`CharacterCard` 改为从 `useUserStore` 读取 `character_slug`，然后 fetch `/api/data/characters/{slug}` 获取完整角色数据。

```ts
// CharacterCard 数据流
useUserStore.character_slug  →  fetch /api/data/characters/{slug}  →  渲染
```

WebSocket 不再负责角色信息推送（Web 端角色管理完全走 REST）。

---

## 与 Bot 端的对比

| 环节 | Bot | Web |
|------|-----|-----|
| 角色创建入口 | 群聊 @bot 自然语言 | "创建角色"按钮 → 对话框 |
| 角色创建接口 | AI tool `draft_character` / `finalize_character` | `POST /api/editor/characters` |
| 角色绑定 | AI tool 自动 | `PUT /api/users/{provider}/{id}/bind` |
| 角色数据源 | `players/{openid}.md` | `.atrpg/users/{provider}/{id}.json` + `data/characters/{slug}.md` |
| 角色卡展示 | 无（纯文本） | 侧边面板 CharacterCard |

**共同点**：角色数据文件格式相同（`data/characters/{slug}.md`），两种创建方式产生的角色互通。
