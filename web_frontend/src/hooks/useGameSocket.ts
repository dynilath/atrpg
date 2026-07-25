/** WebSocket 实时对话 Hook。 */

import { useCallback, useEffect, useRef } from "react";
import { useGameStore, ChatMessage } from "../store/gameStore";

interface UseGameSocketOptions {
  sessionKey?: string;
}

export function useGameSocket(options: UseGameSocketOptions = {}) {
  const wsRef = useRef<WebSocket | null>(null);
  const {
    connected,
    setConnected,
    addMessage,
    appendLastAssistant,
    clearMessages,
  } = useGameStore();

  const sessionKey = options.sessionKey || `player_${Date.now()}`;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws/${sessionKey}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log(`WS connected: ${sessionKey}`);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
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
              content: `⚠ ${msg.payload.message}`,
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

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };

    ws.onerror = () => {
      setConnected(false);
    };
  }, [sessionKey, setConnected, addMessage, appendLastAssistant]);

  const disconnect = useCallback(() => {
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
          content: "⚠ 未连接到服务器",
          timestamp: Date.now(),
        });
        return;
      }

      // 添加用户消息
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

  // 清理
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return {
    connected,
    connect,
    disconnect,
    sendChat,
    clearMessages,
    sessionKey,
  };
}
