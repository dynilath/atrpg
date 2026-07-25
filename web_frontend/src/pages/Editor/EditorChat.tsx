/** 编辑助手 AI 对话面板。 */

import { useState, useRef, useEffect } from "react";

interface EditorChatProps {
  kind: string;
  onCreated: (slug: string) => void;
}

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

const KIND_API: Record<string, string> = {
  "story-arcs": "arcs",
  characters: "characters",
  npcs: "characters",
  items: "items",
  scenes: "scenes",
  locations: "locations",
};

const PROMPT_PLACEHOLDERS: Record<string, string> = {
  "story-arcs": '例如："设计一个码头罢工事件的单局弧光"',
  characters: '例如："创建一个叛逃的帝国法师"',
  npcs: '例如："创建一个港口守夜人队长，外冷内热的老兵"',
  items: '例如："设计一把名为潮汐之刃的魔法剑"',
  scenes: '例如："设计一个地下黑市场景，在码头仓库区"',
  locations: '例如："设计灰港区的地下黑市"',
};

export default function EditorChat({ kind, onCreated }: EditorChatProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");

    const userMsg: ChatMsg = { id: `u-${Date.now()}`, role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const apiEndpoint = KIND_API[kind] || "arcs";
      const body: Record<string, string> = { prompt: text };
      if (kind === "characters") body.type = "pc";
      if (kind === "npcs") body.type = "npc";
      const r = await fetch(`/api/editor/${apiEndpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();

      if (data.ok) {
        const slug = data.slug;
        const title = data.title || slug;
        setMessages((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: `✅ 已创建「${title}」\n\nslug: \`${slug}\``,
          },
        ]);
        onCreated(slug);
      } else {
        setMessages((prev) => [
          ...prev,
          { id: `e-${Date.now()}`, role: "system", content: `⚠ 创建失败: ${data.error || "未知错误"}` },
        ]);
      }
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { id: `e-${Date.now()}`, role: "system", content: `⚠ 请求失败: ${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        marginTop: 12,
        border: "1px solid #0f3460",
        borderRadius: 8,
        background: "#0f1a2e",
        display: "flex",
        flexDirection: "column",
        maxHeight: 400,
      }}
    >
      {/* 消息列表 */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "8px 12px",
          minHeight: 100,
          maxHeight: 280,
        }}
      >
        {messages.length === 0 && (
          <div style={{ color: "#555", fontSize: 12, textAlign: "center", padding: 20 }}>
            用自然语言描述你要创建的内容
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            style={{
              marginBottom: 8,
              padding: "6px 10px",
              borderRadius: 6,
              background:
                m.role === "user"
                  ? "#0a1e3a"
                  : m.role === "assistant"
                  ? "#0a1e1a"
                  : "#2a0a1a",
              borderLeft: `3px solid ${
                m.role === "user" ? "#4a9eff" : m.role === "assistant" ? "#53c0a0" : "#e94560"
              }`,
              fontSize: 12,
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
            }}
          >
            {m.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div
        style={{
          display: "flex",
          gap: 6,
          padding: "8px 12px",
          borderTop: "1px solid #0f3460",
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder={PROMPT_PLACEHOLDERS[kind] || "描述你要创建的内容..."}
          disabled={loading}
          style={{
            flex: 1,
            background: "#1a1a2e",
            color: "#e0e0e0",
            border: "1px solid #0f3460",
            borderRadius: 4,
            padding: "6px 10px",
            fontSize: 13,
            outline: "none",
            fontFamily: "inherit",
          }}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          style={{
            background: loading ? "#333" : "#e94560",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            padding: "6px 14px",
            fontSize: 13,
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading || !input.trim() ? 0.5 : 1,
          }}
        >
          {loading ? "创建中..." : "创建"}
        </button>
      </div>
    </div>
  );
}
