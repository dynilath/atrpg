/** 编辑助手 AI 对话面板。 */

import { useState, useRef, useEffect } from "react";
import { Button, Input } from "../../components/ui";
import ChatMessage from "../../components/ui/ChatMessage";

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
            content: `已创建「${title}」\n\nslug: \`${slug}\``,
          },
        ]);
        onCreated(slug);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `e-${Date.now()}`,
            role: "system",
            content: `创建失败: ${data.error || "未知错误"}`,
          },
        ]);
      }
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "system",
          content: `请求失败: ${e.message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-3 border border-border rounded-lg bg-surface flex flex-col max-h-[400px]">
      <div className="flex-1 overflow-y-auto p-2 px-3 min-h-[100px] max-h-[280px]">
        {messages.length === 0 && (
          <div className="text-xs text-muted-foreground text-center py-5">
            用自然语言描述你要创建的内容
          </div>
        )}
        {messages.map((m) => (
          <ChatMessage key={m.id} role={m.role} content={m.content} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-1.5 p-2 px-3 border-t border-border">
        <Input
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
          className="flex-1 min-w-0 w-auto"
        />
        <Button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          variant={loading ? "secondary" : "primary"}
          size="sm"
        >
          {loading ? "创建中..." : "创建"}
        </Button>
      </div>
    </div>
  );
}
