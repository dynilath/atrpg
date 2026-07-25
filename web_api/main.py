"""main.py — ATRPG Web API 服务入口。

独立 FastAPI 服务：
  - /api/*     → REST API
  - /ws/*      → WebSocket
  - 开发模式：前端由 Vite 独立启动（pnpm dev），通过 Vite proxy 调用后端
  - 生产模式：服务 web_frontend/dist/ 静态文件

用法:
  python run_web.py           # 开发模式（推荐）
  python -m web_api.main      # 或直接启动
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import WebConfig
from .deps import get_config, get_store
from .routes.sessions import router as sessions_router
from .routes.data import router as data_router
from .routes.gm import router as gm_router


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    cfg = get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时：验证 Store 就绪
        try:
            get_store()
            logging.info(f"Store 就绪: {cfg.game_dir}")
        except Exception as e:
            logging.warning(f"Store 初始化失败（仍可启动路由，部分功能不可用）: {e}")
        yield

    app = FastAPI(
        title="ATRPG Web API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── 开发模式：加 CORS 允许 Vite (5173) 跨域访问 ──
    if cfg.web.dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── 注册 API 路由 ──
    app.include_router(sessions_router)
    app.include_router(data_router)
    app.include_router(gm_router)

    # ── 注册 WebSocket 路由 ──
    from .routes.ws import router as ws_router
    app.include_router(ws_router)

    # ── 生产模式：静态文件 ──
    _setup_frontend(app, cfg.web)

    # ── 全局异常处理 ──
    @app.exception_handler(Exception)
    async def global_exception(request: Request, exc: Exception):
        logging.exception("未捕获异常")
        return JSONResponse({"error": f"内部错误: {exc}"}, status_code=500)

    return app


def _setup_frontend(app: FastAPI, web_cfg: WebConfig) -> None:
    """配置前端服务：开发模式不挂载（Vite 独立运行），生产模式用静态文件。"""
    if web_cfg.dev_mode:
        logging.info("开发模式: 前端由 Vite 独立启动（pnpm dev）")
    else:
        _setup_static_files(app)
        logging.info("生产模式: 静态文件 → web_frontend/dist")


def _setup_static_files(app: FastAPI) -> None:
    """生产模式：直接服务 web_frontend/dist/。"""
    from pathlib import Path
    dist = Path(__file__).resolve().parent.parent / "web_frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:
        logging.warning(
            f"前端构建目录不存在: {dist}。请先运行 `cd web_frontend && npm run build`"
        )


def main():
    """启动入口。"""
    cfg = get_config()
    web_cfg = cfg.web

    logging.basicConfig(
        level=getattr(logging, web_cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    app = create_app()
    logging.info(f"启动 Web API: http://{web_cfg.host}:{web_cfg.port}")
    logging.info(f"  API: http://{web_cfg.host}:{web_cfg.port}/api/")
    logging.info(f"  WS:  ws://{web_cfg.host}:{web_cfg.port}/ws/")

    uvicorn.run(
        app,
        host=web_cfg.host,
        port=web_cfg.port,
        log_level=web_cfg.log_level.lower(),
    )


if __name__ == "__main__":
    main()
