"""config.py — web_api 配置加载。

从 bot/config.toml 读取 [web] 和 [atrpg] 段的配置。
独立于 NoneBot 的配置链，供 web_api 自身使用。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 9090
    secret_key: str = "dev-secret"
    dev_mode: bool = True
    vite_url: str = "http://localhost:5173"
    log_level: str = "INFO"
    admin_users: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    game_dir: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-pro"
    llm_utility_model: str = "deepseek-v4-flash"
    web: WebConfig = field(default_factory=WebConfig)


def _find_config() -> Path:
    """从工作目录或项目根向上查找 config.toml。"""
    start = Path.cwd()
    for d in [start, start.parent, start / "bot"]:
        p = d / "config.toml"
        if p.exists():
            return p
    raise FileNotFoundError(
        "找不到 config.toml。请在项目根或 web_api/ 下运行，"
        "或指定 ATRPG_CONFIG 环境变量。"
    )


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载配置。

    优先使用传入路径，否则自动查找。
    支持 env override：ATRPG_CONFIG 指定 config 路径，
    ATRPG_GAME_DIR 覆盖 game_dir。
    """
    import os

    if config_path is None:
        config_path = os.environ.get("ATRPG_CONFIG", "")
        if not config_path:
            config_path = _find_config()
        else:
            config_path = Path(config_path)

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置不存在: {config_path}")

    raw = config_path.read_text(encoding="utf-8")
    cfg = tomllib.loads(raw)

    ac = AppConfig()

    # [atrpg] 段
    atrpg = cfg.get("atrpg", {})
    ac.game_dir = os.environ.get("ATRPG_GAME_DIR", atrpg.get("game_dir", ""))
    ac.llm_base_url = atrpg.get("llm_base_url", ac.llm_base_url)
    ac.llm_api_key = atrpg.get("llm_api_key", ac.llm_api_key)
    ac.llm_model = atrpg.get("llm_model", ac.llm_model)
    ac.llm_utility_model = atrpg.get("llm_utility_model", ac.llm_utility_model)

    # [web] 段
    web = cfg.get("web", {})
    wc = WebConfig()
    wc.host = web.get("host", wc.host)
    wc.port = web.get("port", wc.port)
    wc.secret_key = web.get("secret_key", wc.secret_key)
    wc.dev_mode = web.get("dev_mode", wc.dev_mode)
    wc.vite_url = web.get("vite_url", wc.vite_url)
    wc.log_level = web.get("log_level", wc.log_level)
    wc.admin_users = web.get("admin_users", wc.admin_users)
    ac.web = wc

    return ac
