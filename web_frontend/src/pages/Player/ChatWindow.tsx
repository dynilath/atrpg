/** 消息列表（聊天窗口）。 */

import { useEffect, useRef } from "react";
import { useGameStore } from "../../store/gameStore";
import MarkdownRender from "../../components/MarkdownRender";

const roleColors: Record<string, string> = {
  user: "#4a9eff",
  assistant: "#53c0a0",
  system: "#e94560",
};

const roleBg: Record<string, string> = {
  user: "#0a1e3a",
  assistant: "#0a1e1a",
  system: "#2a0a1a",
};

export default function ChatWindow() {
  const messages = useGameStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#555",
          fontSize: 14,
          padding: 20,
        }}
      >
        <div style={{ textAlign: "center" }}>
          <p style={{ marginBottom: 8, color: "#8a8a9a" }}>🎲 欢迎来到 ATRPG</p>
          <p style={{ fontSize: 12, color: "#666" }}>
            在下方输入框描述你的角色或行动
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "12px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {messages.map((m) => (
        <div
          key={m.id}
          style={{
            padding: "8px 12px",
            borderRadius: 8,
            background: roleBg[m.role] || "#1a1a2e",
            borderLeft: `3px solid ${roleColors[m.role] || "#666"}`,
            maxWidth: "85%",
            alignSelf: m.role === "user" ? "flex-end" : "flex-start",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: roleColors[m.role] || "#666",
              marginBottom: 4,
              fontWeight: "bold",
            }}
          >
            {m.role === "user" ? "你" : m.role === "assistant" ? "主持人" : "系统"}
          </div>
          <MarkdownRender content={m.content} />
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
