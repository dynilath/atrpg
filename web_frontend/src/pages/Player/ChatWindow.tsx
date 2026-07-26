/** 消息列表（聊天窗口）。 */

import { useEffect, useRef, useState } from "react";
import { useGameStore, type ChatMessage } from "../../store/gameStore";
import MarkdownRender from "../../components/MarkdownRender";

export default function ChatWindow() {
  const messages = useGameStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const prevLen = useRef(messages.length);

  useEffect(() => {
    // 新消息到来时自动滚到底部
    if (messages.length > prevLen.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevLen.current = messages.length;
  }, [messages.length]);

  const loadMore = async () => {
    if (!hasMore || loadingMore) return;
    setLoadingMore(true);
    try {
      const oldest = messages[0];
      const beforeId = oldest?.id?.replace("chat-", "");
      const r = await fetch(`/api/config/chat?before=${beforeId || ""}&limit=50`);
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      if (data.messages && data.messages.length > 0) {
        const store = useGameStore.getState();
        const chatMsgs: ChatMessage[] = data.messages.map(
          (m: { id: number; ts: string; sender: string; text: string; source: string }) => ({
            id: `chat-${m.id}`,
            role: (m.source === "bot" ? "assistant" : m.source === "web" ? "user" : "system") as ChatMessage["role"],
            content: m.text,
            timestamp: new Date(m.ts).getTime(),
            sender: m.sender,
          })
        );
        store.addMessages(chatMsgs);
        if (chatMsgs.length < 50) setHasMore(false);
      } else {
        setHasMore(false);
      }
    } catch {
      // ignore
    } finally {
      setLoadingMore(false);
    }
  };

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm p-5">
        <div className="text-center">
          <p className="mb-2">欢迎来到 ATRPG</p>
          <p className="text-xs opacity-70">在下方输入框描述你的角色或行动</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto flex flex-col">
      {hasMore && (
        <div className="text-center py-2">
          <button
            onClick={loadMore}
            disabled={loadingMore}
            className="text-xs text-muted-foreground hover:text-fg px-3 py-1"
          >
            {loadingMore ? "加载中..." : "加载更多"}
          </button>
        </div>
      )}
      <div className="flex-1 p-3 px-4 flex flex-col gap-2">
        {messages.map((m) => (
          <div key={m.id} className={`flex flex-col gap-0.5 ${m.role === "user" ? "items-end" : "items-start"}`}>
            {m.sender && (
              <span className={`text-xs px-1 ${
                m.role === "assistant" ? "text-primary" : m.role === "user" ? "text-muted-foreground" : "text-muted-foreground"
              }`}>
                {m.sender}
              </span>
            )}
            <div className={`rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words max-w-[85%] ${
              m.role === "user"
                ? "bg-primary-container text-fg self-end"
                : m.role === "assistant"
                ? "bg-surface-dim text-fg self-start"
                : "bg-surface-dim border border-border text-muted-foreground text-xs self-center max-w-full"
            }`}>
              <MarkdownRender content={m.content} />
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
