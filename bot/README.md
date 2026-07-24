# ATRPG Bot

QQ 群 AI 主持人验证程序。吃一个符合 `agent.md` 规划的 TRPG 上下文目录，接 QQ 官方 Bot API，在群里当主持人带团。

## 设计依据

- 运行时设计：`../proposals/qq-runtime-design.md`
- 工作流规范：`../agent.md`
- QQ 接入参考：[openhanako](https://github.com/liliMozi/openhanako) 的 `lib/bridge/qq-adapter.ts`（腾讯官方 Bot API）

## 目录结构

```
bot/
├── config.toml               # 配置（QQ appID/appSecret、LLM key、上下文目录路径；含密钥，gitignore）
├── pyproject.toml            # 项目元数据 + [tool.nonebot] 插件声明
├── run.py                    # 启动入口（读 config.toml → nonebot.init 注入）
├── config_setup.py           # 交互式配置向导（读写 config.toml）
└── atrpg_gm/
    ├── __init__.py
    ├── store.py              # TRPG 上下文目录加载与持久化
    ├── llm.py               # OpenAI 兼容 LLM 客户端
    ├── arc.py                # 弧光分级规划与追踪
    ├── gm.py                # 主持人核心调度（工具调用驱动：角色创建/行动裁决/落盘）
    └── gm_runtime.md         # 运行时系统提示词
└── example-game/            # 示例 TRPG 上下文目录（含 1 条主要弧光 + 场景/地点）
    └── data/
        ├── characters/  npcs/  locations/  scenes/  items/
        ├── story-arcs/        # 主要弧光由备团用户预置；次要局部/单局由主持人运行时生成
        ├── state-records/
        ├── sessions/          # 群号↔团会话
        └── players/           # QQ↔角色绑定
```

## 安装

venv 建在项目内（自包含，迁移/删除方便）：

```bash
cd bot
# 用系统 Python 创建项目内 venv（需 Python >=3.11，依赖内置 tomllib 读 config.toml）
"C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m venv .venv
# 装依赖到项目 venv
.venv\Scripts\python.exe -m pip install nonebot2 nonebot-adapter-qq pyyaml openai httpx tomli-w
```

之后运行 `pwsh -File run.ps1` 即可（自动用项目内 venv 的 Python，无需手动激活）。

## 配置

**首次运行无需手动改配置** —— 启动时若检测到 config.toml 缺失或关键字段为占位符（appID/AppSecret/LLM key/上下文目录等），会自动进入交互式向导：

```
$ pwsh -File run.ps1

⚠ 未找到 config.toml，进入首次配置向导。

==================================================
  ATRPG Bot 首次配置向导
==================================================

=== QQ 机器人配置 ===
腾讯官方提供扫码登录页，无需手动在 q.qq.com 翻找：

  扫码页地址：https://q.qq.com/qqbot/openclaw/login.html

操作步骤：
  1. 浏览器打开上面的链接
  2. 用手机 QQ 扫描页面二维码登录（扫码的 QQ 须实名）
  3. 进入控制台后点「创建机器人」，填名称/头像/描述
  4. 创建成功后，复制 AppID 与 AppSecret（AppSecret 首次只显示一次，务必保存）
  5. 回到这里，把 Appid / AppSecret 粘到下方提示
  ...

是否现在打开 QQ 机器人扫码页？
  1.是，打开扫码页 / 2.否，我已有 AppID/AppSecret
> 1
→ 已尝试用默认浏览器打开扫码页：https://q.qq.com/qqbot/openclaw/login.html
  若未自动打开，请手动复制上方地址到浏览器。

AppID [扫码登录→创建机器人后，控制台显示的 AppID]
> 102345678
AppSecret [首次生成后只能看一次，务必保存；同时填入 token 与 secret]
> ********
```

向导完成后自动写入 `config.toml` 并继续启动。

> **关于 toml 配置**：NoneBot 2.5 原生不支持从 toml 读配置值（只支持 `.env` / 环境变量 / `init(**kwargs)`）。本程序在 `run.py` 里自读 `config.toml`，拍平后通过 `nonebot.init(**kwargs)` 注入——init kwargs 优先级最高，可靠覆盖。这样配置文件干净可读（toml 原生多行/内联表），不用 dotenv 那套转义 JSON。

### 手动改 config.toml（可选）

跳过向导直接编辑 `config.toml`：

```toml
# NoneBot 运行参数
[nonebot]
driver = "~httpx+~websockets"
host = "127.0.0.1"
port = 8080
log_level = "INFO"
qq_is_sandbox = false

# QQ 官方 Bot（在 https://q.qq.com 注册机器人，取 appID/appSecret）
# adapter-qq 约定：token 与 secret 都填 AppSecret
[[qq_bots]]
id = "你的APPID"
token = "你的AppSecret"
secret = "你的AppSecret"
use_websocket = true
  [qq_bots.intent]
  c2c_group_at_messages = true

# ATRPG 运行时
[atrpg]
game_dir = "./example-game"        # 指向一个符合 agent.md 的 TRPG 上下文目录
target_group = ""                  # 只响应这个群（留空则响应所有）

# LLM（OpenAI 兼容协议）
llm_base_url = "https://open.bigmodel.cn/api/paas/v4"
llm_api_key = "your-key"
llm_model = "glm-4-plus"
llm_utility_model = "glm-4-flash"
```

## 运行

```bash
cd bot
pwsh -File run.ps1            # 推荐：PowerShell 脚本，自动用项目 venv
# 或：powershell -File run.ps1
# 或直接：.venv\Scripts\python.exe run.py
```

启动后会校验 `game_dir`：至少 1 条主要弧光 + 若干场景/地点，否则拒绝开团。

### 获取群 openid（重要，无法预先查）

QQ 官方群的 openid **不能预先查到**，只能从 bot 收到的消息事件里提取。流程：

1. `config.toml` 里 `[atrpg] target_group = ""` 留空（响应所有群）
2. 在 QQ 开放平台「沙箱配置」把测试群加进去（你须是群主/管理员，群≤20人）
3. 手机 QQ 把机器人添加进群，在群里 @机器人 发一条消息
4. bot 日志会打印 `group_openid=xxxxx`（32 位十六进制）
5. 把 openid 抄进 `config.toml` 的 `[atrpg] target_group`，重启，此后只响应这个群

或用 `pwsh -File run.ps1 -Setup` 重跑向导填回来。

任何时候想重跑向导：`pwsh -File run.ps1 -Setup`

## TRPG 上下文目录约定

详见 `../agent.md` 与 `../templates/`。最小要求：

```
<game-dir>/
├── templates/                # 角色/弧光/状态/场景模板（可从 ../templates/ 复制）
└── data/
    ├── story-arcs/*.md        # ★ 至少 1 条 级别:主要 的弧光（备团用户预置）
    ├── locations/*.md         # 至少 1 个地点
    ├── scenes/*.md            # 至少 1 个场景
    └── characters/ npcs/ items/ state-records/ sessions/ players/   # 运行时生成
```

## 玩家用法

在群里 @bot：

- `@bot 我是个流浪剑客，在找失散的妹妹` → 角色创建（首次）
- `@bot 我劝说守卫放行` → 行动处理（已绑定）
- `@bot /角色` → 查看自己角色卡
- `@bot /我在哪` → 查看当前场景与在场者
- `@bot /回顾` → 主持人总结最近剧情
- `@bot /弧光` → 当前弧光平衡报告（管理员）

## 弧光分级（主持人权限）

| 级别 | 谁规划 | 说明 |
|------|--------|------|
| 次要局部 | 主持人 ✓ | 单场景局部互动（如讨价还价），可不收尾 |
| 单局 | 主持人 ✓ | 任务/冒险，1~3 次聚会 |
| 主要 | 备团用户 | 跨多场高层次，主持人只跑+追踪 |

主持人不可：规划主要弧光、改写任何弧光蓝图、把次要升级为主要。

## 验证清单

| # | 点 | 自测方式 |
|---|----|----|
| R1 | 开放加入 | 新 QQ @bot 概括叙述 → 生成角色卡、绑定、AI 定初始场景 |
| R2 | 行动裁决 | 已绑定 @bot 行动 → 裁决+扮 NPC+推进，落盘对话 |
| R3 | 场景归属 | 跨场景声明被拦截并给路径 |
| R4 | 弧光追踪 | 行动触发主要弧光阶段推进时，弧光档案被更新 |
| R5 | 支撑创作 | 主持人创建配角/道具/场景，落盘标注 |
| R6 | 蓝图不可改 | 全程未改写任何弧光四阶段 |
| R7 | 持久化 | 重启后 `/我在哪` 准确 |
| R8 | 偏离处理 | 偏离主要弧光时标记 pending_director |
| R9 | 受限规划 | 涌现时新建次要局部/单局弧光，标注级别/规划者/平衡检查 |

## 注意

- QQ 官方 Bot 群聊仅返回 openid（非真实 QQ 号），`players/` 文件以 openid 为 key。
- 群@消息是被动回复，需用 `msg_id`+`msg_seq` 关联，5 分钟内有效。
- 文本按 1900 字分块发送。
- 依赖在 venv 隔离，不污染系统 Python。
