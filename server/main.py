"""main.py --- ATRPG Web API 服务入口。

FastAPI 应用工厂：
  - /api/*     -> REST API
  - /ws/*      -> WebSocket
  - 开发模式：前端由 Vite 独立启动（pnpm dev），通过 Vite proxy 调用后端
  - 生产模式：服务 web_frontend/dist/ 静态文件

可被 NoneBot (bot/run.py) 挂载到其 FastAPI driver 上，
也可独立启动（python -m server.main）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .deps import get_config, get_store


def create_app(force_dev_mode: bool | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用。

    force_dev_mode: None=读 config.toml; True=强制开发模式; False=强制生产模式。
    """
    cfg = get_config()
    dev_mode = cfg.dev_mode if force_dev_mode is None else force_dev_mode

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时：验证 Store 就绪 + 启动 QQ Bot
        try:
            get_store()
            logging.info(f"Store 就绪: {cfg.game_dir}")
        except Exception as e:
            logging.warning(f"Store 初始化失败: {e}")

        from .qqbot import get_qqbot
        qqbot = get_qqbot()
        await qqbot.start()

        yield

        # 关闭时
        await qqbot.stop()

    app = FastAPI(
        title="ATRPG Web API",
        version="0.2.0",
        lifespan=lifespan,
    )

    # ── 开发模式：加 CORS 允许 Vite (5173) 跨域访问 ──
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ── 注册 API 路由 ──
    from .routes.sessions import router as sessions_router
    from .routes.data import router as data_router
    from .routes.gm import router as gm_router
    from .routes.editor import router as editor_router
    from .routes.users import router as users_router
    from .routes.config_routes import router as config_router

    app.include_router(sessions_router)
    app.include_router(data_router)
    app.include_router(gm_router)
    app.include_router(editor_router)
    app.include_router(users_router)
    app.include_router(config_router)

    # ── 注册 WebSocket 路由 ──
    from .routes.ws import router as ws_router
    app.include_router(ws_router)

    # ── 前端服务 ──
    _setup_frontend(app, dev_mode)

    # ── 全局异常处理 ──
    @app.exception_handler(Exception)
    async def global_exception(request: Request, exc: Exception):
        logging.exception("未捕获异常")
        return JSONResponse({"error": f"内部错误: {exc}"}, status_code=500)

    return app


def _setup_frontend(app: FastAPI, dev_mode: bool) -> None:
    """配置前端服务：开发模式不挂载（Vite 独立运行），生产模式用静态文件。"""
    if dev_mode:
        logging.info("开发模式: 前端由 Vite 独立启动（pnpm dev），通过 http://localhost:5173 访问")
    else:
        _setup_static_files(app)
        logging.info("生产模式: 静态文件 -> web_frontend/dist")


def _setup_static_files(app: FastAPI) -> None:
    """生产模式：直接服务 web_frontend/dist/。"""
    from pathlib import Path
    dist = Path(__file__).resolve().parent.parent / "web_frontend" / "dist"
    if not dist.exists():
        logging.warning(f"前端构建目录不存在: {dist}")
        return

    # 资产文件用 StaticFiles
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    # 根路径和 SPA 回退用路由
    from fastapi.responses import FileResponse, HTMLResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        p = (dist / full_path).resolve()
        if str(p).startswith(str(dist.resolve())) and p.is_file():
            return FileResponse(str(p))
        index = dist / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return HTMLResponse("Not Found", status_code=404)

    logging.info(f"前端静态文件已挂载: {dist}")


def main():
    """独立启动入口。"""
    import tomllib
    cfg = get_config()
    config_path = Path(__file__).resolve().parent.parent / "config.toml"
    sc = {}
    if config_path.exists():
        sc = tomllib.loads(config_path.read_text(encoding="utf-8")).get("server", {})

    logging.basicConfig(
        level=getattr(logging, sc.get("log_level", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    app = create_app()
    host = sc.get("host", "127.0.0.1")
    port = sc.get("port", 8080)
    logging.info(f"启动 Web API: http://{host}:{port}")
    logging.info(f"  API: http://{host}:{port}/api/")
    logging.info(f"  WS:  ws://{host}:{port}/ws/")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=sc.get("log_level", "INFO").lower(),
    )


if __name__ == "__main__":
    main()
