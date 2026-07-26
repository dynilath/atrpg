# 游戏聊天室与 LLM 会话分支

## 架构原则

- **无 game_id**：程序启动时即确定唯一游戏目录，无需路由级区分
- **WS 连接用 `?uid={userId}` 参数区分用户**，而非在路径里编码 session
- **聊天室存 SQLite**（`.atrpg/chat.db`），一条消息一行
- **LLM 会话用 open-webui 消息树模型**：`{id, parentId, childrenIds[]}`，分支即多子节点

## 数据模型

### 聊天室（SQLite）

`.atrpg/chat.db`：

```sql
CREATE TABLE messages (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT    NOT NULL,   -- ISO 8601
  sender    TEXT    NOT NULL,   -- "林默" / "主持人" / "系统"
  text      TEXT    NOT NULL,
  source    TEXT    NOT NULL DEFAULT 'web'   -- 'web' | 'qq' | 'bot'
);
```

- `source='bot'` = AI 主持人回复，前端渲染为 assistant 样式
- `source='web'` = Web 端玩家发送
- `source='qq'` = QQ 群消息（未来互通）

### LLM 会话分支（open-webui 消息树模型）

```
.atrpg/sessions/
├── main.db                 ← SQLite: 消息树 + 分支元数据
└── snapshots/              ← 每个 turn 完整消息快照（LLM 上下文）
    ├── 001.json
    ├── 002.json
    └── ...
```

**消息树表**（参考 open-webui）：

```sql
CREATE TABLE tree_nodes (
  id          TEXT PRIMARY KEY,       -- UUID
  parent_id   TEXT,                   -- 父节点 id（null = root）
  turn_no     INTEGER NOT NULL,       -- 轮次编号（显示用，不决定顺序）
  branch_id   TEXT NOT NULL DEFAULT 'main',
  snapshot_path TEXT,                 -- snapshots/{turn_no}.json
  meta        TEXT,                   -- JSON: {timestamp, sender, player_text, reply_preview, usage}
  FOREIGN KEY (parent_id) REFERENCES tree_nodes(id)
);
```

**分支表**：

```sql
CREATE TABLE branches (
  id          TEXT PRIMARY KEY,       -- 'main', 'branch-002', ...
  name        TEXT NOT NULL,
  head_id     TEXT NOT NULL,          -- 当前活跃叶子节点 id
  created_at  TEXT NOT NULL,
  FOREIGN KEY (head_id) REFERENCES tree_nodes(id)
);

CREATE TABLE active_branch (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  branch_id TEXT NOT NULL,
  FOREIGN KEY (branch_id) REFERENCES branches(id)
);
```

**树结构示例**：

```
     001 (main)
       │
     002 (main)
     ┌─┴──┐
   003   005 (branch-002)  ← active
    │     │
   004   006
```

- `003` 和 `005` 都是 `002` 的孩子（`parent_id = 002的id`）
- `childrenIds` 不显式存，通过 `parent_id` 反向查询
- 活跃分支的 `head_id` 指向 `006`，遍历时从 `006` 反向走到根

### 与 open-webui 的差异

| open-webui | ATRPG |
|---|---|
| 每条消息一个节点 | 每个 turn（玩家+AI回复）一个节点 |
| 支持消息级编辑 | 支持 turn 级回滚 |
| currentId 指向当前叶子 | head_id 指向分支末端 |
| 前端按分支箭头切换 | 控制台树状图交互 |

## WebSocket 协议

### 端点

```
ws://host/ws?uid={userId}
```

- 无需在路径编码 session，uid 参数区分连接
- 同一游戏目录下所有 WS 连接共享聊天室
- identify 消息保持不变（provider + uid）

### 消息流

```
客户端 → {type:"chat", payload:{text:"..."}}
  → 服务端: 写 chat.db (source=web)
  → 广播所有 WS: {type:"chat_msg", payload:{...}}
  → 触发 process_turn(text)
  → 流式 reply_chunk 推回发送者
  → process_turn 完成
  → 写 chat.db (source=bot, sender="主持人")
  → 广播所有 WS: {type:"chat_msg", payload:{...}}
```

### 新增消息类型

```json
// 连接时推送最近 N 条历史
{"type":"chat_history","payload":{"messages":[...]}}

// 广播：有人发了新消息
{"type":"chat_msg","payload":{"id":123,"ts":"...","sender":"林默","text":"...","source":"web"}}
```

## 控制台树状图设计

### 布局

- 垂直时间轴 + 水平分支
- 节点间用 **贝塞尔曲线**（`d="M x1,y1 C cx1,cy1 cx2,cy2 x2,y2"`）连接
- 活跃分支用主色高亮，非活跃用灰色
- 节点卡片显示：`#003` + 时间戳 + 发送人 + 预览文字

### 交互

- **点击节点** → 右侧展开该 turn 的完整消息详情
- **右键节点** → 菜单：[从此回滚（开新分支）] [切换到此分支]
- **分支切换** → 更新 `active_branch`，后续对话走新分支
- **回滚** → 创建新分支（head 指向选中节点），设为 active

### 曲线连接示意

```
 ┌──────┐
 │ #002 │
 └──┬───┘
    │ ╲          ← 贝塞尔曲线（不是折线）
    │  ╲
 ┌──┴──┐  ┌──────┐
 │#003 │  │ #005 │
 └──┬──┘  └──┬───┘
    │        │
 ┌──┴──┐  ┌──┴──┐
 │#004 │  │#006 │ ← active (高亮)
 └─────┘  └─────┘
```

## 实施步骤

1. **Phase A：存储层** — SQLite chat.db + 消息树
2. **Phase B：数据迁移** — 73DBF47A18FDB3952E6216395D5F263F → 新结构
3. **Phase C：后端路由** — ws.py 改 `?uid=` + 聊天室广播
4. **Phase D：前端聊天室** — ChatWindow 历史加载 + 实时消息流 + 多人共享
5. **Phase E：控制台重构** — 贝塞尔曲线树状图 + 分支创建/切换
6. **Phase F：调试验证**
