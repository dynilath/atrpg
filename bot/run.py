"""ATRPG Bot 启动入口（toml 配置版）。

启动流程：
1. config_setup.ensure_config() 校验 config.toml 完整性（缺失则走交互式向导）
2. 把 config.toml 拍平成 nonebot.init(**kwargs) 注入 NoneBot
   —— NoneBot 2.5 原生不支持从 toml 读配置值，但 init kwargs 优先级最高，可靠覆盖。
3. 注册 QQ 官方适配器
4. load_from_toml 读 pyproject.toml 的 [tool.nonebot] 加载插件
5. run

用法：
    python run.py            # 启动（首次缺失配置自动走向导）
    python run.py --setup    # 强制重跑配置向导
"""

from __future__ import annotations

import sys
from typing import Any

# 注意：config_setup 必须独立于 atrpg_gm 插件包导入。
# 若在 nonebot.load_from_toml() 之前 import atrpg_gm 的任何子模块，
# 会触发 "Module atrpg_gm is not loaded as a plugin" 错误。
import config_setup

# ATRPG [atrpg] 表里的键 → nonebot Config 期望的小写属性名前缀
# atrpg.llm_base_url  →  atrpg_llm_base_url
# atrpg.game_dir      →  atrpg_game_dir
_ATRPG_KEY_MAP = {
    "llm_base_url": "atrpg_llm_base_url",
    "llm_api_key": "atrpg_llm_api_key",
    "llm_model": "atrpg_llm_model",
    "llm_utility_model": "atrpg_llm_utility_model",
    "game_dir": "atrpg_game_dir",
    "target_group": "atrpg_target_group",
    "c2c_test_mode": "atrpg_c2c_test_mode",
}


def _flatten_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """把 config.toml 的三个 table 拍平成 nonebot.init(**kwargs)。

    [nonebot]   → host/port/driver/log_level/qq_is_sandbox
    [[qq_bots]] → qq_bots（list[BotInfo]，手动构造——InitSettingsSource 不做深度转换）
    [atrpg]     → atrpg_llm_base_url / atrpg_game_dir 等（小写前缀）
    """
    # BotInfo 必须手动构造：init(**kwargs) 走 InitSettingsSource，传 list[dict]
    # 会被原样存为 dict，而 adapter 内部用属性访问（bot_info.id / .intent.to_int()）
    # 会 AttributeError。所以这里把 toml 的 dict 转成 BotInfo 对象。
    from nonebot.adapters.qq.config import BotInfo, Intents

    nb = cfg.get("nonebot", {})
    bots_raw = cfg.get("qq_bots", [])
    qq_bots: list[BotInfo] = []
    for b in bots_raw:
        intent_raw = b.get("intent", {}) or {}
        qq_bots.append(
            BotInfo(
                id=str(b["id"]),
                token=str(b["token"]),
                secret=str(b["secret"]),
                intent=Intents(**intent_raw),
                use_websocket=b.get("use_websocket", True),
            )
        )

    kwargs: dict[str, Any] = {
        "driver": nb.get("driver", "~fastapi+~httpx+~websockets"),
        "host": nb.get("host", "127.0.0.1"),
        "port": nb.get("port", 8080),
        "log_level": nb.get("log_level", "INFO"),
        "qq_is_sandbox": nb.get("qq_is_sandbox", False),
        "qq_bots": qq_bots,
    }

    atrpg = cfg.get("atrpg", {})
    for toml_key, config_key in _ATRPG_KEY_MAP.items():
        if toml_key in atrpg:
            val = atrpg[toml_key]
            # target_group 在 toml 里可能是字符串或数字，统一转 str
            if toml_key == "target_group":
                val = str(val) if val != "" else ""
            kwargs[config_key] = val

    return kwargs


def main() -> None:
    force_setup = "--setup" in sys.argv or "--reconfig" in sys.argv
    cfg = config_setup.ensure_config(force=force_setup)

    # 延迟到此处再 import nonebot，确保 config.toml 已就绪
    import nonebot
    from nonebot.adapters.qq import Adapter as QQAdapter

    kwargs = _flatten_config(cfg)
    nonebot.init(**kwargs)
    driver = nonebot.get_driver()
    driver.register_adapter(QQAdapter)
    nonebot.load_from_toml("pyproject.toml")

    # 挂载网页控制台（在 FastAPI driver 的 server_app 上加路由）
    from atrpg_gm.console import setup_console
    setup_console()

    nonebot.run()


if __name__ == "__main__":
    main()
