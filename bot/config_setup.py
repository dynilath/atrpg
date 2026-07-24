"""config_setup.py — 交互式配置向导。

启动时若 .env 缺失或关键字段为占位符，走交互式向导引导用户填配置。
写回 .env 后返回，由启动入口继续 nonebot.init()。

注：本模块独立于 atrpg_gm 插件包，避免在 NoneBot 加载插件前提前导入
atrpg_gm 包（否则会触发 "Module atrpg_gm is not loaded as a plugin" 错误）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["ensure_config", "ConfigError"]

ENV_PATH = Path(__file__).resolve().parent / ".env"

# 占位符列表：出现这些值视为"未配置"
_PLACEHOLDERS = {"your-llm-key", "your_app_id", "your_app_token", "your_app_secret", "123456789", ""}

# 默认值（向导给出建议）
_DEFAULTS = {
    "HOST": "127.0.0.1",
    "PORT": "8080",
    "LOG_LEVEL": "INFO",
    "DRIVER": "~httpx+~websockets",
    "QQ_IS_SANDBOX": "false",
    "ATRPG_LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "ATRPG_LLM_MODEL": "glm-4-plus",
    "ATRPG_LLM_UTILITY_MODEL": "glm-4-flash",
}


class ConfigError(Exception):
    """配置不完整。"""


def _read_env() -> dict[str, str]:
    """读 .env 为 dict（不依赖 python-dotenv，简单解析）。"""
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _is_placeholder(val: str | None) -> bool:
    if val is None:
        return True
    v = val.strip().strip("'\"").lower()
    return v in _PLACEHOLDERS or v.startswith("your_")


def _missing_fields(env: dict[str, str]) -> list[str]:
    """返回未配置的关键字段。"""
    missing = []
    # QQ_BOTS 里的占位符
    qq_bots = env.get("QQ_BOTS", "")
    if _is_placeholder(qq_bots) or "YOUR_APP_ID" in qq_bots or "YOUR_APP_TOKEN" in qq_bots or "YOUR_APP_SECRET" in qq_bots:
        missing.append("QQ_BOTS")
    for key in ("ATRPG_LLM_API_KEY", "ATRPG_GAME_DIR", "ATRPG_TARGET_GROUP"):
        if _is_placeholder(env.get(key)):
            missing.append(key)
    return missing


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
        # 也接受直接输入选项文本
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
        "  - 下方 AppSecret 同时填入 token 与 secret 两个字段（adapter-qq 约定）\n"
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


def _wizard() -> dict[str, str]:
    """跑完整向导，返回配置 dict。"""
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
    print("    d) bot 日志会打印 group_openid=xxxxx，抄回来填进 .env 的 ATRPG_TARGET_GROUP")
    print("    e) 重启 bot，此后只响应这个群")
    target_group = _prompt("目标群 openid", default="",
                           hint="先留空（直接回车）；拿到 openid 后再 python run.py --setup 填回来")

    # 4. LLM
    print("\n=== LLM 配置（OpenAI 兼容协议） ===")
    print("  支持 GLM / DeepSeek / 通义 / Kimi 等，填 base_url + api_key 即可")
    base_url = _prompt("LLM base_url", default=_DEFAULTS["ATRPG_LLM_BASE_URL"])
    api_key = _prompt("LLM API key", hint="如 GLM: 在 open.bigmodel.cn 申请")
    model = _prompt("对话模型", default=_DEFAULTS["ATRPG_LLM_MODEL"])
    utility_model = _prompt("轻量模型", default=_DEFAULTS["ATRPG_LLM_UTILITY_MODEL"])

    # QQ_BOTS 存为紧凑 JSON 字符串，由 _write_env 负责转义写入 .env
    bots_config = [
        {
            "id": app_id,
            "token": app_secret,
            "secret": app_secret,
            "intent": {"c2c_group_at_messages": True},
            "use_websocket": True,
        }
    ]
    return {
        "QQ_BOTS": json.dumps(bots_config, ensure_ascii=False),
        "ATRPG_GAME_DIR": game_dir,
        "ATRPG_TARGET_GROUP": target_group,
        "ATRPG_LLM_BASE_URL": base_url,
        "ATRPG_LLM_API_KEY": api_key,
        "ATRPG_LLM_MODEL": model,
        "ATRPG_LLM_UTILITY_MODEL": utility_model,
    }


def _write_env(values: dict[str, str]) -> None:
    """把配置写回 .env（保留默认项 + 用户值）。"""
    lines = [
        "# ATRPG Bot 配置（由 setup 向导生成）",
        "",
        f"HOST={_DEFAULTS['HOST']}",
        f"PORT={_DEFAULTS['PORT']}",
        f"LOG_LEVEL={_DEFAULTS['LOG_LEVEL']}",
        f"DRIVER={_DEFAULTS['DRIVER']}",
        "QQ_IS_SANDBOX=false",
        "",
        "# QQ 机器人（appID/AppSecret）",
        "# python-dotenv 不支持三引号，用双引号包裹并转义内部双引号",
        "QQ_BOTS=\"" + values["QQ_BOTS"].replace("\\", "\\\\").replace('"', '\\"') + "\"",
        "",
        "# ATRPG 运行时",
        f"ATRPG_GAME_DIR={values['ATRPG_GAME_DIR']}",
        f"ATRPG_TARGET_GROUP={values['ATRPG_TARGET_GROUP']}",
        "",
        "# LLM（OpenAI 兼容）",
        f"ATRPG_LLM_BASE_URL={values['ATRPG_LLM_BASE_URL']}",
        f"ATRPG_LLM_API_KEY={values['ATRPG_LLM_API_KEY']}",
        f"ATRPG_LLM_MODEL={values['ATRPG_LLM_MODEL']}",
        f"ATRPG_LLM_UTILITY_MODEL={values['ATRPG_LLM_UTILITY_MODEL']}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 配置已写入 {ENV_PATH}")


def ensure_config(force: bool = False) -> None:
    """启动前调用。配置缺失则走向导；齐全则直接返回。

    force=True 时强制重跑向导（用于重新配置）。
    """
    env = _read_env()
    missing = _missing_fields(env) if not force else list(_DEFAULTS.keys()) + ["QQ_BOTS"]

    if not missing:
        return

    if missing:
        print(f"\n⚠ 检测到未配置项: {', '.join(missing)}")
        values = _wizard()
        _write_env(values)
        # 写入后重新加载到 os.environ，供 nonebot.init() 读取
        for k, v in values.items():
            os.environ[k] = v
        print("\n✓ 配置完成，即将启动 bot...")