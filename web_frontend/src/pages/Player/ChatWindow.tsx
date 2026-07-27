/** 消息列表（聊天窗口）。 */

import { useEffect, useRef, useState } from "react";
import { useGameStore, type ChatMessage } from "../../store/gameStore";
import MarkdownRender from "../../components/MarkdownRender";

/* ------------------------------------------------------------------ */
/*  角色颜色工具                                                       */
/* ------------------------------------------------------------------ */

/**
 * 基于字符串生成稳定的 HSL 色相（0-360）。
 */
function strHue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffff;
  return h % 360;
}

function charColorsFor(slug: string, colorMap: Record<string, number>): { bg: string; nameColor: string } {
  const hue = colorMap[slug] != null ? colorMap[slug] : strHue(slug);
  return { bg: `hsl(${hue}, 28%, 94%)`, nameColor: `hsl(${hue}, 45%, 35%)` };
}

/** 消息来源 → 对齐方式 */
type Align = "left" | "right" | "center";
function msgAlign(msg: ChatMessage): Align {
  if (msg.role === "assistant") return "left";
  if (msg.role === "user") return "right";
  return "center";
}

/* ------------------------------------------------------------------ */
/*  组件                                                               */
/* ------------------------------------------------------------------ */

export default function ChatWindow() {
  const messages = useGameStore((s) => s.messages);
  const charColors = useGameStore((s) => s.charColors);
  const setCharColors = useGameStore((s) => s.setCharColors);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const prevLen = useRef(messages.length);
  const colorsLoaded = useRef(false);

  // 独立加载角色颜色映射（不依赖 PlayerPage 的加载时序）
  useEffect(() => {
    if (colorsLoaded.current) return;
    fetch("/api/data/characters")
      .then((r) => r.json())
      .then((data) => {
        const list = Array.isArray(data) ? data : data.characters || [];
        const colorMap: Record<string, number> = {};
        list.forEach((c: { slug: string; meta: Record<string, unknown> }) => {
          if (c.meta["color"] != null) colorMap[c.slug] = Number(c.meta["color"]);
        });
        setCharColors(colorMap);
        colorsLoaded.current = true;
      })
      .catch(() => {});
  }, [setCharColors]);

  useEffect(() => {
    if (messages.length > prevLen.current) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" } as ScrollIntoViewOptions);
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
          (m: { id: number; ts: string; sender: string; text: string; source: string; character?: string }) => ({
            id: `chat-${m.id}`,
            role: (m.source === "bot" ? "assistant" : m.source === "web" || m.source === "qq" ? "user" : "system") as ChatMessage["role"],
            content: m.text,
            timestamp: new Date(m.ts).getTime(),
            sender: m.sender,
            character: m.character,
            source: m.source,
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
        {messages.map((m) => {
          const align = msgAlign(m);
          const sender = m.sender || "";
          const isBoundChar = !!m.character;
          const colors = isBoundChar ? charColorsFor(m.character!, charColors) : null;

          const containerCls =
            align === "left" ? "items-start" :
            align === "right" ? "items-end" : "items-center";

          let bubbleCls: string;
          if (m.role === "user" && isBoundChar) {
            bubbleCls = "self-end max-w-[85%]";
          } else if (m.role === "user" && !isBoundChar) {
            bubbleCls = "bg-surface-dim border border-border text-muted-foreground self-end max-w-[85%]";
          } else if (m.role === "assistant") {
            bubbleCls = "bg-surface-dim text-fg self-start max-w-[85%]";
          } else {
            bubbleCls = "bg-surface-dim border border-border text-muted-foreground text-xs self-center max-w-full";
          }

          return (
            <div key={m.id} className={`flex flex-col gap-0.5 ${containerCls}`}>
              {/* 发送者名 */}
              {sender && (
                <span
                  className="text-xs px-1"
                  style={isBoundChar && colors ? { color: colors.nameColor, fontWeight: 500 } : { color: "var(--color-muted-foreground)" }}
                >
                  {m.role === "assistant" ? `🎭 ${sender}` :
                   align === "right" ? sender :
                   sender}
                </span>
              )}
              {/* 气泡 */}
              <div
                className={`rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${bubbleCls}`}
                style={m.role === "user" && isBoundChar && colors ? { backgroundColor: colors.bg, color: "var(--color-fg)" } : undefined}
              >
                <MarkdownRender content={m.content} />
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
