import { useState, useEffect, useRef, useCallback } from "react";
import { MessageCircle, X, Send, Loader2 } from "lucide-react";
import MarkdownRender from "../../components/MarkdownRender";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

export default function EditorAIPanel() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      fetch("/api/editor/chat")
        .then((r) => r.json())
        .then((d) => setMessages(d.messages || []))
        .catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    try {
      const resp = await fetch("/api/editor/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await resp.json();
      if (data.reply) {
        setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: `[错误] ${data.error || "未知错误"}` }]);
      }
    } catch (e: any) {
      setMessages((prev) => [...prev, { role: "assistant", content: `[网络错误] ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* 浮动按钮 */}
      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-6 left-6 z-50 w-12 h-12 rounded-full bg-primary text-white
                   shadow-lg hover:shadow-xl hover:scale-105 active:scale-95
                   flex items-center justify-center transition-all duration-200"
        title="AI 辅助编辑"
      >
        {open ? <X size={20} /> : <MessageCircle size={20} />}
      </button>

      {/* 居中悬浮窗口 */}
      {open && (
        <>
          {/* 遮罩 */}
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setOpen(false)}
          />
          {/* 窗口 */}
          <div
            className="fixed inset-0 z-40 flex items-center justify-center pointer-events-none"
          >
            <div
              className="pointer-events-auto w-[720px] max-h-[85vh]
                          bg-surface rounded-2xl shadow-2xl border border-border
                          flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-surface-elevated shrink-0">
                <span className="font-semibold">AI 辅助编辑</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted">{messages.length} 条消息</span>
                  <button
                    onClick={() => setOpen(false)}
                    className="text-muted-foreground hover:text-fg transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                {messages.length === 0 && (
                  <div className="text-center text-muted text-sm mt-24">
                    向 AI 助手提问，辅助你设计弧光、角色、NPC、物品、情境、地点等。
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[85%] px-4 py-3 rounded-xl text-sm leading-relaxed ${
                        m.role === "user"
                          ? "bg-primary-container text-primary-on-container"
                          : "bg-surface-elevated text-foreground border border-border"
                      }`}
                    >
                      {m.role === "assistant" ? (
                        <MarkdownRender content={m.content} />
                      ) : (
                        <span>{m.content}</span>
                      )}
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-surface-elevated border border-border rounded-xl px-4 py-3 flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin text-muted" />
                      <span className="text-muted text-sm">思考中...</span>
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {/* Input */}
              <div className="px-4 py-3 border-t border-border bg-surface shrink-0">
                <div className="flex gap-2">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="描述你的需求..."
                    rows={2}
                    disabled={loading}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-border bg-surface
                               text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/30
                               placeholder:text-muted disabled:opacity-50"
                  />
                  <button
                    onClick={handleSend}
                    disabled={loading || !input.trim()}
                    className="shrink-0 w-10 h-10 rounded-xl bg-primary text-white
                               flex items-center justify-center
                               hover:bg-primary-hover disabled:opacity-40 transition-colors"
                  >
                    <Send size={16} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
