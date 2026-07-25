"""web_api — ATRPG 独立 Web API 服务。

独立于 NoneBot 进程运行的 FastAPI 服务，
复用 bot/atrpg_gm/ 下的核心模块（store/arc/llm/process_turn/工具表）。
提供 REST API（/api/*）和 WebSocket（/ws/*），
开发模式下反向代理 Vite 前端（/ → Vite dev server）。
"""
