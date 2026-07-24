# ATRPG Bot 实现现状

> 本文档记录 QQ 群 AI 主持人验证程序（`bot/`）的实际实现状态。
> 原始设计见 `qq-runtime-design.md`（保留作设计参考，不随实现改动）。
> 最近更新：2026-07-25

---

## 1. 技术栈与架构

| 层 | 选型 |
|----|------|
| Bot 框架 | NoneBot 2.5 + `nonebot-adapter-qq` 1.7 |
| QQ 接入 | 腾讯官方 Bot API（WebSocket 客户端 + REST 发送） |
| LLM | OpenAI 兼容协议（当前用 DeepSeek `deepseek-v4-pro`） |
| 配置 | `bot/config.toml`（toml，自建注入层 → `nonebot.init(**kwargs)`） |
| HTTP 控制台 | FastAPI（内嵌于 NoneBot driver，`~fastapi+~httpx+~websockets`） |
| 数据持久化 | `data/` 下 markdown + YAML front matter（数据源） |
| 运行时缓存 | `.atrpg/` 下 JSON（对话历史快照，非数据源） |
| Python | 3.13（内置 `tomllib` 读 toml） |

### 进程模型
单进程：NoneBot（含 FastAPI uvicorn HTTP 服务 + QQ WebSocket 出站连接）。
- `127.0.0.1:8080` 同时承载：控制台网页 + QQ 适配器事件循环。
- QQ 连接是出站 WebSocket，不占端口。

---

## 2. 目录结构

```
bot/
├── config.toml               # 配置（QQ/LLM/游戏目录/控制台，含密钥，gitignore）
├── pyproject.toml            # 项目元数据 + [tool.nonebot] 插件声明
├── run.py                    # 启动入口（读 toml → nonebot.init 注入 → 挂控制台 → run）
├── config_setup.py           # 交互式配置向导（读写 config.toml）
├── build_world_book.py       # 世界书 + 文风参考预处理脚本（单次，开发阶段）
├── migrate_history.py        # 旧扁平历史迁移脚本（已用完，保留备用）
├── requirements.txt          # 依赖锁定
└── atrpg_gm/
    ├── __init__.py           # 包入口（import .gm 注册 matcher）
    ├── store.py              # TRPG 目录读写门面 + 历史快照 + 位置追踪
    ├── llm.py                # OpenAI 兼容客户端 + tool-calling 循环 + usage
    ├── arc.py                # 弧光分级规划与追踪
    ├── gm.py                 # 主持人核心调度（matcher + 14 工具 + handler）
    ├── gm_runtime.md         # 运行时系统提示词（身份/工具指引/文风）
    └── console.py            # 网页控制台（FastAPI 路由 + 单页 HTML）
```

### 游戏目录结构（`<game-dir>/`）
```
├── pdf_extract_*.txt          # 原始规则书 PDF 提取文本（世界材料源）
├── data/
│   ├── world-book.md          # 世界书（build_world_book.py 总结生成，常驻设定）
│   ├── style-guide.md         # 文风参考（同上，叙事调性 + 摘抄样本）
│   ├── characters/<slug>.md   # 玩家角色（含草案，状态:待确认/正式）
│   ├── npcs/                  # NPC
│   ├── locations/             # 地点
│   ├── scenes/                # 场景（含在场者字段）
│   ├── items/                 # 道具
│   ├── story-arcs/            # 故事弧光（主要/单局/次要局部）
│   ├── state-records/         # 状态变化记录
│   ├── sessions/              # 群号↔团会话
│   └── players/               # QQ↔角色绑定
└── .atrpg/                    # 运行时缓存（非数据源）
    └── history/
        └── <session_key>/
            ├── current.json   # 当前活跃历史（截断版，供 LLM 续接）
            └── snapshots/
                └── turn-NNN.json  # 每轮快照（完整 messages + meta + usage）
```

---

## 3. 配置（config.toml）

```toml
[nonebot]
driver = "~fastapi+~httpx+~websockets"   # FastAPI 控制台 + HTTP 客户端 + WS 客户端
host = "127.0.0.1"
port = 8080
log_level = "INFO"
qq_is_sandbox = false

[[qq_bots]]                     # QQ 官方 Bot（token/secret 都填 AppSecret）
id = "..."
token = "..."
secret = "..."
use_websocket = true
  [qq_bots.intent]
  c2c_group_at_messages = true

[atrpg]
game_dir = "..."                # 游戏目录路径
target_group = "..."            # 目标群 openid（留空响应所有群）
c2c_test_mode = true            # 私聊测试开关（验证用，正式跑团关闭）
llm_base_url = "..."
llm_api_key = "..."
llm_model = "deepseek-v4-pro"
llm_utility_model = "deepseek-v4-flash"
```

**配置加载链**：`run.py` 读 `config.toml`（`tomllib`）→ `_flatten_config` 拍平成小写 kwargs（含手动构造 `list[BotInfo]`）→ `nonebot.init(**kwargs)` 注入（优先级最高）。

---

## 4. 核心机制实现

### 4.1 消息处理流程
```
玩家 @bot / 私聊
  → matcher（on_message + is_type(GroupAtMessageCreateEvent | C2CMessageCreateEvent)）
  → _resolve_session：群@用 group_openid，私聊用 c2c_<openid>
  → c2c_test_mode 开关过滤（私聊）
  → target_group 过滤（群@）
  → 加载历史（load_history，清洗孤立 tool 消息）
  → 构造 messages：稳定 system 前缀（gm_runtime + 世界书 + 文风参考）
    + 历史正文（剥 system）+ 本轮 <turn> 发送人框架
  → 工具调用循环（MAX_TOOL_ROUNDS=6）：
      LLM chat_with_tools → 执行 tool_calls → 回灌 result → 继续
      reply 工具立即发群（流式），落盘工具后台继续
  → save_history（快照 + current.json）
  → 分块发送兜底
```

### 4.2 发送人框架
每轮玩家消息以 `<turn>` 标签包装，含最小信息：
```xml
<turn sender="角色名" char="char-slug" | 当前场景: 场景名>
状态: 已绑定角色（身份）

玩家说的内容
</turn>
```
场景描写/在场者/弧光详情**不自动喂**——LLM 用 `query_locations`/`query_memory` 按需查。

### 4.3 流式回复
- `reply` 工具被调用时**立即发群**（通过 `send_fn` 包装 `matcher.send`）。
- LLM 应先 reply 演绎文本，再调落盘工具。
- 一轮只调一次 reply（QQ 对同 msg_id 快速连续回复会去重）。
- `_send` 捕获去重错误（40054005）不冒泡，避免 LLM 重试循环。

### 4.4 对话历史与缓存
- **稳定前缀**：`gm_runtime.md` + 世界书 + 文风参考 → system 消息，每轮不变，命中 DeepSeek 前缀缓存。
- **历史续接**：`current.json` 存截断版历史（MAX=40，保留首条 system + 最近 20 条，截断点保证 tool_calls/tool 配对完整）。
- **快照**：每轮保存完整未截断 messages + meta（轮号/时间/发送人/玩家文本/reply预览/usage）到 `snapshots/turn-NNN.json`。
- **token 用量**：每轮累加所有 LLM 调用的 usage（prompt/completion/cached_tokens），日志输出 + 快照记录。

### 4.5 角色创建（草案即落盘 + 输出分离）
- `draft_character`：直接写 `data/characters/<slug>.md`（状态:待确认，body 含全量含剧情钩子）。发群只发**玩家可见摘要卡**（不含钩子/秘密）。
- `finalize_character`：从 characters/ 读草案，改状态为正式，绑定 QQ↔角色，设场景归属。
- 跨消息有效——玩家这一轮没确认，下一轮说"确认"也能 finalize。

### 4.6 弧光分级
| 级别 | 规划者 | 工具 |
|------|--------|------|
| 主要 | 备团用户预置 | `track_arc`（只追踪，不改蓝图） |
| 单局 | 主持人 | `plan_arc`（受限，红线检查+平衡检查） |
| 次要局部 | 主持人 | `plan_arc` |

字段兼容：`级别`/`类型`，`主要`/`主要弧光` 等多种写法归一化。

### 4.7 位置追踪
- `query_locations` 工具：`where_is`（角色在哪）/ `who_in`（场景有谁）/ `all`（所有角色位置）。
- store 层：`char_scene`（正向）+ `chars_in_scene`（反向，读场景在场者）+ `all_char_locations`。

---

## 5. 工具清单（14 个）

| 工具 | 作用 |
|------|------|
| `reply` | 发消息给玩家（唯一出口，流式立即发群） |
| `draft_character` | 生成角色卡草案并落盘（状态:待确认） |
| `finalize_character` | 草案转正式（绑定+场景归属） |
| `append_scene_dialogue` | 追加场景对话记录 |
| `move_character_scene` | 角色场景转移 |
| `create_npc` / `create_item` / `create_scene` / `create_location` | 支撑创作（落盘标注性质） |
| `record_state` | 状态变化记录（连接原则） |
| `track_arc` | 弧光阶段追踪 |
| `plan_arc` | 规划次要局部/单局弧光 |
| `query_memory` | 检索 data/ 档案 |
| `query_locations` | 角色位置/场景在场者查询 |

---

## 6. 网页控制台

访问 `http://127.0.0.1:8080/console/`，功能：
- **会话列表**：扫描 `.atrpg/history/` 下的 session
- **轮次列表**：每轮显示时间/发送人/玩家发言预览/reply预览/用量
- **总计用量**：输入/输出/缓存命中数+命中率
- **轮次详情**：完整 messages（system/user/assistant/tool 分色显示，tool_calls 参数展开）
- **回滚**：回滚到某轮（删除后续快照，current.json 恢复）

---

## 7. 世界书与文风参考

`build_world_book.py <game-dir>` 读取 `pdf_extract_*.txt`，调 LLM 生成：
- `data/world-book.md`：结构化世界书（世界观/阵营/规则/术语/地点/NPC类型）
- `data/style-guide.md`：文风参考（文风特征/摘抄样本/模仿要点）

两者作为稳定 system 前缀注入 LLM，类似 SillyTavern 常驻世界书。

---

## 8. 已知问题与设计偏差

| 问题 | 状态 | 说明 |
|------|------|------|
| LLM 偶尔把演绎文本写在消息正文而非 reply 参数 | 已缓解 | schema + gm_runtime 强调，reply 空值检查返回明确错误 |
| QQ 消息去重（40054005） | 已缓解 | `_send` 吞错误不冒泡，gm_runtime 强调一轮一次 reply |
| 收尾残留文本（"处理完毕"） | 已缓解 | 兜底逻辑丢弃已 reply 后的残留文本 |
| 私聊（C2C）支持 | 已实现 | c2c_test_mode 开关，用虚拟 session 隔离 |
| 控制台无鉴权 | 待办 | 本地 127.0.0.1，验证阶段可接受 |
| 多群并行 | 未实现 | 当前单群/单私聊，设计文档留给生产阶段 |

---

## 9. 验证清单状态（对照 qq-runtime-design.md §10）

| # | 验证点 | 状态 |
|---|--------|------|
| R1 | 开放加入 | ✅ draft+finalize，草案跨消息确认 |
| R2 | 行动裁决 | ✅ append_scene_dialogue + reply |
| R3 | 场景归属 | ✅ move_character_scene + 跨场景约束指引 |
| R4 | 弧光追踪 | ✅ track_arc |
| R5 | 支撑创作 | ✅ create_npc/item/scene/location |
| R6 | 蓝图不可改 | ✅ track_arc 只追加，gm_runtime 约束 |
| R7 | 持久化 | ✅ store 落盘 + 重启后历史续接 |
| R8 | 偏离处理 | ✅ record_state + pending_director 指引 |
| R9 | 受限规划 | ✅ plan_arc 红线+平衡检查 |
