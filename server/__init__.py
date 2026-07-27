"""server --- ATRPG Web API 服务层。

提供 FastAPI REST API + WebSocket 路由。
被 bot/run.py 挂载到 NoneBot 的 FastAPI driver 上，
也可独立启动（python -m server.main）。
"""
