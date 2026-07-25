/** 行动输入框。 */

import { useState, useRef, useEffect } from "react";
import { useGameStore } from "../../store/gameStore";
import { useGameSocket } from "../../hooks/useGameSocket";

interface ActionInputProps {
  socket: ReturnType<typeof useGameSocket>;
}

export default function ActionInput({ socket }: ActionInputProps) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState(1);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const connected = useGameStore((s) => s.connected);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      const lineHeight = 20;
      const newRows = Math.min(
        Math.max(1, Math.floor(textareaRef.current.scrollHeight / lineHeight)),
        8
      );
      setRows(newRows);
    }
  }, [text]);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || !connected) return;
    socket.sendChat(trimmed);
    setText("");
    setRows(1);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      style={{
        padding: "8px 12px",
        borderTop: "1px solid #0f3460",
        background: "#16213e",
        display: "flex",
        gap: 8,
        alignItems: "flex-end",
      }}
    >
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          connected
            ? "描述你的行动、对话或提问..."
            : "正在连接服务器..."
        }
        disabled={!connected}
        rows={rows}
        style={{
          flex: 1,
          background: "#1a1a2e",
          color: "#e0e0e0",
          border: "1px solid #0f3460",
          borderRadius: 6,
          padding: "8px 12px",
          fontSize: 14,
          fontFamily: "inherit",
          resize: "none",
          outline: "none",
          lineHeight: 1.5,
          minHeight: 36,
          maxHeight: 160,
        }}
      />
      <button
        onClick={handleSend}
        disabled={!connected || !text.trim()}
        style={{
          background: connected ? "#e94560" : "#333",
          color: "#fff",
          border: "none",
          borderRadius: 6,
          padding: "8px 16px",
          fontSize: 14,
          cursor: connected ? "pointer" : "not-allowed",
          opacity: connected && text.trim() ? 1 : 0.5,
          whiteSpace: "nowrap",
          height: 36,
        }}
      >
        发送
      </button>
    </div>
  );
}
