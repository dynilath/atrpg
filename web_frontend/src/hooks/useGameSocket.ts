/** WebSocket 实时对话 Hook — 自动管理连接生命周期。 */

import { useCallback, useEffect, useRef } from "react";
import { useGameStore, ChatMessage } from "../store/gameStore";

interface UseGameSocketOptions {
  provider?: string;
  userId?: string;
}

export function useGameSocket(options: UseGameSocketOptions = {}) {
  const wsRef = useRef<WebSocket | null>(null);
  const connectingRef = useRef(false);
  const {
    connected,
    setConnected,
    addMessage,
    appendLastAssistant,
    clearMessages,
  } = useGameStore();

  const provider = options.provider || "";
  const userId = options.userId || "";

  const connect = useCallback(() => {
    if (!userId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (wsRef.current?.readyState === WebSocket.CONNECTING) return;
    if (connectingRef.current) return;

    connectingRef.current = true;

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws?uid=${encodeURIComponent(userId)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log(`WS connected: uid=${userId}, identifying as ${provider}:${userId}`);
      connectingRef.current = false;
      ws.send(JSON.stringify({ type: "identify", payload: { provider, openid: userId } }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        console.debug(`WS ← ${msg.type}`, msg.payload || "");
        switch (msg.type) {
          case "connected":
            setConnected(true, msg.session_key);
            break;
          case "reply_chunk":
            appendLastAssistant(msg.payload.text);
            break;
          case "reply_done":
            setConnected(true);
            break;
          case "error":
            addMessage({
              id: `error-${Date.now()}`,
              role: "system",
              content: msg.payload.message,
              timestamp: Date.now(),
            });
            break;
          case "pong":
          case "heartbeat":
            break;
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = (e) => {
      console.log(`WS closed: uid=${userId} code=${e.code} reason=${e.reason}`);
      connectingRef.current = false;
      setConnected(false);
      wsRef.current = null;
    };

    ws.onerror = (e) => {
      console.error("WS error:", e);
      connectingRef.current = false;
      setConnected(false);
    };
  }, [userId, provider, setConnected, addMessage, appendLastAssistant]);

  const disconnect = useCallback(() => {
    connectingRef.current = false;
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, [setConnected]);

  const sendChat = useCallback(
    (text: string, mode: "chat" | "edit" = "chat") => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        addMessage({
          id: `error-${Date.now()}`,
          role: "system",
          content: "未连接到服务器",
          timestamp: Date.now(),
        });
        return;
      }

      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: text,
        timestamp: Date.now(),
      };
      addMessage(userMsg);

      ws.send(JSON.stringify({ type: mode, payload: { text } }));
    },
    [addMessage]
  );

  useEffect(() => {
    if (userId) { connect(); }
    return () => { disconnect(); };
  }, [userId, connect, disconnect]);

  return {
    connected,
    connect,
    disconnect,
    sendChat,
    clearMessages,
  };
}
