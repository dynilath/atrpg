/** 消息列表（聊天窗口）。 */

import { useEffect, useRef } from "react";
import { useGameStore } from "../../store/gameStore";
import ChatMessage from "../../components/ui/ChatMessage";
import MarkdownRender from "../../components/MarkdownRender";

export default function ChatWindow() {
  const messages = useGameStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

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
    <div className="flex-1 overflow-y-auto p-3 px-4 flex flex-col gap-2">
      {messages.map((m) => (
        <ChatMessage
          key={m.id}
          role={m.role}
          content={<MarkdownRender content={m.content} />}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
