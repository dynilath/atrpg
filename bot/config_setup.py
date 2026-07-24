"""config_setup.py — 交互式配置向导（toml 版）。

启动时若 config.toml 缺失或关键字段为占位符，走交互式向导引导用户填配置，
写回 config.toml。run.py 读取 config.toml 后通过 nonebot.init(**kwargs) 注入。

注：本模块独立于 atrpg_gm 插件包，避免在 NoneBot 加载插件前提前导入
atrpg_gm 包（否则会触发 "Module atrpg_gm is not loaded as a plugin" 错误）。

配置文件结构见 config.toml：
  [nonebot]   — NoneBot 运行参数
  [[qq_bots]] — QQ 机器人列表（appID/AppSecret）
  [atrpg]     — ATRPG 运行时 + LLM 配置
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

__all__ = ["ensure_config", "load_config", "ConfigError", "CONFIG_PATH"]

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

# 占位符：出现这些值视为"未配置"
_PLACEHOLDERS = {"your-llm-key", "your_app_id", "your_app_token", "your_app_secret", "123456789", ""}

# 默认值（向导给出建议）
_DEFAULTS = {
    "driver": "~httpx+~websockets",
    "host": "127.0.0.1",
    "port": 8080,
    "log_level": "INFO",
    "qq_is_sandbox": False,
    "llm_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "llm_model": "glm-4-plus",
    "llm_utility_model": "glm-4-flash",
}


class ConfigError(Exception):
    """配置不完整或格式错误。"""


# ---------------------------------------------------------------------------
# 读取 / 校验
# ---------------------------------------------------------------------------

def _is_placeholder(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        v = val.strip().lower()
        return v in _PLACEHOLDERS or v.startswith("your_")
    return False


def load_config() -> dict[str, Any]:
    """读取并解析 config.toml，返回完整 dict。

    文件不存在或格式错误时抛 ConfigError。
    """
    if not CONFIG_PATH.exists():
        raise ConfigError(f"配置文件不存在：{CONFIG_PATH}（请运行向导：python run.py --setup）")
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config.toml 格式错误：{e}") from e


def _missing_fields(cfg: dict[str, Any]) -> list[str]:
    """返回未配置的关键字段。"""
    missing: list[str] = []

    bots = cfg.get("qq_bots", [])
    if not bots or not isinstance(bots, list):
        missing.append("qq_bots")
    else:
        bot = bots[0]
        for k in ("id", "token", "secret"):
            if _is_placeholder(bot.get(k)):
                missing.append(f"qq_bots.{k}")
                break

    atrpg = cfg.get("atrpg", {})
    for key in ("llm_api_key", "game_dir", "target_group"):
        if _is_placeholder(atrpg.get(key)):
            missing.append(f"atrpg.{key}")

    return missing


# ---------------------------------------------------------------------------
# 交互式向导
# ---------------------------------------------------------------------------

def _prompt(label: str, default: str = "", hint: str = "") -> str:
    """交互式输入，支持默认值。"""
    suffix = f" [{default}]" if default else ""
    hint_str = f"\n  {hint}" if hint else ""
    while True:
        val = input(f"{label}{suffix}{hint_str}\n> ").strip()
        if not val and default:
            return default
        if val:
            return val
        print("  不能为空，请重新输入。")


def _prompt_choice(label: str, choices: list[str], hint: str = "") -> str:
    """交互式选择。"""
    hint_str = f"\n  {hint}" if hint else ""
    opts = " / ".join(f"{i+1}.{c}" for i, c in enumerate(choices))
    while True:
        val = input(f"{label}\n  {opts}{hint_str}\n> ").strip()
        if val.isdigit() and 1 <= int(val) <= len(choices):
            return choices[int(val) - 1]
        for c in choices:
            if val.lower() == c.lower():
                return c
        print("  无效选择，请输入序号。")


def _print_qq_scan_help() -> None:
    """打印 QQ Bot 扫码连接/手动填的指引。"""
    print(
        "\n=== QQ 机器人配置 ===\n"
        "腾讯官方提供扫码登录页，无需手动在 q.qq.com 翻找：\n"
        "\n"
        "  扫码页地址：https://q.qq.com/qqbot/openclaw/login.html\n"
        "\n"
        "操作步骤：\n"
        "  1. 浏览器打开上面的链接\n"
        "  2. 用手机 QQ 扫描页面二维码登录（扫码的 QQ 须实名）\n"
        "  3. 进入控制台后点「创建机器人」，填名称/头像/描述\n"
        "  4. 创建成功后，复制 AppID 与 AppSecret（AppSecret 首次只显示一次，务必保存）\n"
        "  5. 回到这里，把 AppID / AppSecret 粘到下方提示\n"
        "\n"
        "提示：\n"
        "  - 每个 QQ 号最多创建 5 个机器人\n"
        "  - 沙箱测试需在控制台「沙箱配置」指定你是群主/管理员的群（≤20 人）\n"
        "  - 正式上线需配 IP 白名单（运行 bot 的机器公网 IP）；沙箱免白名单\n"
        "  - 下方 AppSecret 同时填入 token 与 secret（adapter-qq 约定）\n"
    )


def _maybe_open_scan_page() -> None:
    """尝试自动用浏览器打开扫码页（失败不报错，用户可手动开）。"""
    url = "https://q.qq.com/qqbot/openclaw/login.html"
    import webbrowser
    try:
        opened = webbrowser.open(url)
        if opened:
            print(f"\n→ 已尝试用默认浏览器打开扫码页：{url}")
            print("  若未自动打开，请手动复制上方地址到浏览器。\n")
            return
    except Exception:
        pass
    print(f"\n→ 请手动在浏览器打开扫码页：{url}\n")


def _wizard() -> dict[str, Any]:
    """跑完整向导，返回配置 dict（结构同 config.toml）。"""
    print("\n" + "=" * 50)
    print("  ATRPG Bot 首次配置向导")
    print("=" * 50)

    # 1. QQ Bot —— 先问是否打开扫码页
    _print_qq_scan_help()
    choice = _prompt_choice(
        "是否现在打开 QQ 机器人扫码页？",
        choices=["是，打开扫码页", "否，我已有 AppID/AppSecret"],
        hint="选「是」会用默认浏览器打开 https://q.qq.com/qqbot/openclaw/login.html",
    )
    if choice.startswith("是"):
        _maybe_open_scan_page()

    app_id = _prompt("AppID", hint="扫码登录→创建机器人后，控制台显示的 AppID")
    app_secret = _prompt("AppSecret", hint="首次生成后只能看一次，务必保存；同时填入 token 与 secret")

    # 2. TRPG 上下文目录
    print("\n=== TRPG 上下文目录 ===")
    print("  指向一个符合 agent.md 规划的目录（含 data/ 与至少 1 条主要弧光）")
    game_dir = _prompt("游戏目录路径", default="./example-game",
                       hint="可用内置示例 ./example-game 先跑通")

    # 3. 目标群（openid 无法预先查，要先留空跑起来再抄）
    print("\n=== 目标群 openid ===")
    print("  QQ 官方群的 openid 无法预先查询，只能从 bot 收到的消息事件里提取。")
    print("  建议流程：")
    print("    a) 先留空（响应所有群）")
    print("    b) 在 QQ 开放平台「沙箱配置」把你的测试群加进去（你须是群主/管理员，群≤20人）")
    print("    c) 手机 QQ 把机器人添加进群，在群里 @机器人 发一条消息")
    print("    d) bot 日志会打印 group_openid=xxxxx，抄回来填进 config.toml 的 target_group")
    print("    e) 重启 bot，此后只响应这个群")
    target_group = _prompt("目标群 openid", default="",
                           hint="先留空（直接回车）；拿到 openid 后再 python run.py --setup 填回来")

    # 4. 私聊测试开关
    print("\n=== 私聊测试模式 ===")
    print("  开启后，bot 也响应 C2C 私聊消息（用虚拟会话隔离），方便不依赖群环境快速验证。")
    print("  正式跑团应关闭。")
    c2c_test = _prompt_choice(
        "是否开启私聊测试模式？",
        choices=["是，开启（验证用）", "否，仅群@消息"],
        hint="验证阶段建议开启",
    )
    c2c_test_mode = c2c_test.startswith("是")

    # 5. LLM
    print("\n=== LLM 配置（OpenAI 兼容协议） ===")
    print("  支持 GLM / DeepSeek / 通义 / Kimi 等，填 base_url + api_key 即可")
    base_url = _prompt("LLM base_url", default=_DEFAULTS["llm_base_url"])
    api_key = _prompt("LLM API key", hint="如 GLM: 在 open.bigmodel.cn 申请")
    model = _prompt("对话模型", default=_DEFAULTS["llm_model"])
    utility_model = _prompt("轻量模型", default=_DEFAULTS["llm_utility_model"])

    return {
        "nonebot": {
            "driver": _DEFAULTS["driver"],
            "host": _DEFAULTS["host"],
            "port": _DEFAULTS["port"],
            "log_level": _DEFAULTS["log_level"],
            "qq_is_sandbox": _DEFAULTS["qq_is_sandbox"],
        },
        "qq_bots": [
            {
                "id": app_id,
                "token": app_secret,
                "secret": app_secret,
                "intent": {"c2c_group_at_messages": True},
                "use_websocket": True,
            }
        ],
        "atrpg": {
            "game_dir": game_dir,
            "target_group": target_group,
            "c2c_test_mode": c2c_test_mode,
            "llm_base_url": base_url,
            "llm_api_key": api_key,
            "llm_model": model,
            "llm_utility_model": utility_model,
        },
    }


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------

def _write_toml(cfg: dict[str, Any]) -> None:
    """把配置 dict 写回 config.toml（用 tomli_w 序列化）。"""
    import tomli_w
    CONFIG_PATH.write_text(tomli_w.dumps(cfg), encoding="utf-8")
    print(f"\n✓ 配置已写入 {CONFIG_PATH}")


def ensure_config(force: bool = False) -> dict[str, Any]:
    """启动前调用。配置缺失则走向导；齐全则返回解析后的配置 dict。

    force=True 时强制重跑向导（用于重新配置）。
    返回的 dict 由 run.py 拍平后传给 nonebot.init(**kwargs)。
    """
    if force:
        cfg = _wizard()
        _write_toml(cfg)
        print("\n✓ 配置完成，即将启动 bot...")
        return cfg

    try:
        cfg = load_config()
    except ConfigError:
        print(f"\n⚠ 未找到 config.toml，进入首次配置向导。")
        cfg = _wizard()
        _write_toml(cfg)
        print("\n✓ 配置完成，即将启动 bot...")
        return cfg

    missing = _missing_fields(cfg)
    if missing:
        print(f"\n⚠ 检测到未配置项: {', '.join(missing)}")
        cfg = _wizard()
        _write_toml(cfg)
        print("\n✓ 配置完成，即将启动 bot...")

    return cfg
