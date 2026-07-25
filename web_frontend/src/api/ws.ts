/** WebSocket 客户端。

开发模式下连接到同域 /ws/ 端点（由 FastAPI 代理处理）。
*/

export function connectWs(sessionKey: string): WebSocket {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws/${sessionKey}`;
  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log(`WebSocket 已连接: ${sessionKey}`);
  };

  ws.onclose = () => {
    console.log(`WebSocket 已断开: ${sessionKey}`);
  };

  ws.onerror = (e) => {
    console.error("WebSocket 错误:", e);
  };

  // 心跳保活
  const interval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    } else {
      clearInterval(interval);
    }
  }, 25000);

  ws.addEventListener("close", () => clearInterval(interval));

  return ws;
}
