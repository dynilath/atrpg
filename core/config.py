"""config.py --- 统一配置加载。

从项目根目录 config.toml 读取 [nonebot] / [atrpg] 段配置。
被 core/、server/、bot/ 共同使用。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    game_dir: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-pro"
    llm_utility_model: str = "deepseek-v4-flash"
    dev_mode: bool = True
    admin_users: list[str] = field(default_factory=list)


def _find_config() -> Path:
    """从项目根目录或工作目录查找 config.toml。"""
    import os

    # 优先：项目根（基于本文件位置推算）
    proj_root = Path(__file__).resolve().parent.parent
    p = proj_root / "config.toml"
    if p.exists():
        return p

    # 回退：工作目录及父目录
    start = Path(os.getcwd())
    for d in [start, start.parent, start / "bot"]:
        p = d / "config.toml"
        if p.exists():
            return p
    raise FileNotFoundError(
        "找不到 config.toml。请放在项目根目录或指定 ATRPG_CONFIG 环境变量。"
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
    ac.admin_users = atrpg.get("admin_users", ac.admin_users)

    # [server] 段
    server = cfg.get("server", {})
    ac.dev_mode = server.get("dev_mode", ac.dev_mode)

    return ac
