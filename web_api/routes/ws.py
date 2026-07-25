"""ws.py — /ws/* WebSocket 路由。

实时消息推送：主持人回复流式到达、QQ 消息实时观察等。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/{session_key}")
async def session_ws(websocket: WebSocket, session_key: str):
    """WebSocket 端点：建立连接后保持心跳，供前端实时接收推送。

    客户端可发送 "ping" 保活（服务端回复 "pong"）。
    服务端每 30 秒发一次 "heartbeat" 检查连接状态。
    当前为连接管理骨架，后续添加消息推送。
    """
    await websocket.accept()
    await websocket.send_json({"type": "connected", "session_key": session_key})
    logging.info(f"WebSocket 已连接: {session_key}")

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # 发心跳保活
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
    except WebSocketDisconnect:
        logging.debug(f"WebSocket 断开: {session_key}")
    except Exception as e:
        logging.debug(f"WebSocket 异常: {session_key} — {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
