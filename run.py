"""ATRPG 统一启动入口。

uvicorn 跑 FastAPI（Web API + WebSocket），始终运行。
QQ Bot 在 server/qqbot.py 中通过 FastAPI lifespan 按需启动。

用法：
    python run.py                             # 启动
    python run.py --game-dir <path>           # 指定游戏工作目录
    python run.py --log-file <path>           # 指定日志文件
    python run.py --setup                     # 强制重跑配置向导
    python run.py --dist                      # 生产模式：服务 web_frontend/dist/
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 强制 UTF-8 编码（Windows 默认 cp1252/GBK 会导致日志乱码）
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _parse_cli_arg(flag: str) -> str | None:
    try:
        idx = sys.argv.index(flag)
        return sys.argv[idx + 1]
    except (ValueError, IndexError):
        return None


def main() -> None:
    force_setup = "--setup" in sys.argv or "--reconfig" in sys.argv
    is_dist = "--dist" in sys.argv
    game_dir_override = _parse_cli_arg("--game-dir")
    log_file_override = _parse_cli_arg("--log-file")

    if game_dir_override:
        import os
        os.environ["ATRPG_GAME_DIR"] = game_dir_override

    # 配置向导
    if str(_PROJECT_ROOT / "bot") not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT / "bot"))
    from config_setup import ensure_config
    cfg = ensure_config(force=force_setup)
    if game_dir_override:
        cfg.setdefault("atrpg", {})["game_dir"] = game_dir_override

    # 读取服务配置
    sc = cfg.get("server", {})
    host = sc.get("host", "127.0.0.1")
    port = sc.get("port", 8080)
    log_level = sc.get("log_level", "INFO").upper()

    # ---- 统一日志系统 ----
    _setup_logging(log_level, log_file_override)

    logger = logging.getLogger("atrpg")

    # 启动前输出绑定令牌
    from core.config import load_config
    acfg = load_config()
    if acfg.game_dir:
        from core.token_bind import current_token, bound_group
        token = current_token(acfg.game_dir)
        bound = bound_group(acfg.game_dir)
        if bound:
            logger.info(f"已绑定群: {bound}")
        logger.info(f"群绑定令牌: {token}")
        logger.info("在 QQ 群中 @bot 发送此令牌即可绑定当前游戏目录")

    # 启动 FastAPI（uvicorn 主进程）
    import uvicorn
    from server.main import create_app

    app = create_app(force_dev_mode=None if not is_dist else False)
    logger.info(f"ATRPG 启动: http://{host}:{port}")
    if game_dir_override:
        logger.info(f"游戏目录: {game_dir_override}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=_uvicorn_log_config(),
        log_level=log_level.lower(),
    )


def _setup_logging(level: str, cli_log_file: str | None = None) -> None:
    """配置统一日志系统：控制台 + 文件。

    优先级：--log-file 参数 > config.toml server.log_file > logs/atrpg.log
    """
    import tomllib
    log_file_path = _PROJECT_ROOT / "logs" / "atrpg.log"

    if cli_log_file:
        p = Path(cli_log_file)
        log_file_path = p if p.is_absolute() else _PROJECT_ROOT / p
    else:
        try:
            raw = tomllib.loads((_PROJECT_ROOT / "config.toml").read_text(encoding="utf-8"))
            cfg_path = raw.get("server", {}).get("log_file", "")
            if cfg_path:
                p = Path(cfg_path)
                log_file_path = p if p.is_absolute() else _PROJECT_ROOT / p
        except Exception:
            pass

    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s | %(message)s",
        datefmt="%m-%d %H:%M:%S",
    )

    # 控制台（stdout → run.ps1 管道自动捕获写入 logs/atrpg.log）
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # 文件：始终写入（不依赖 isatty，确保 UTF-8 编码）
    try:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file_path), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass  # 文件不可写时不影响控制台输出


def _uvicorn_log_config() -> dict:
    """返回 uvicorn 日志配置，使其通过根 logger 输出（统一走同一个 handler 体系）。"""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.error": {"handlers": [], "level": "INFO", "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "INFO", "propagate": True},
        },
    }


if __name__ == "__main__":
    main()
