/** 行动输入框。 */

import { useState, useRef, useEffect } from "react";
import { useGameStore } from "../../store/gameStore";
import { useGameSocket } from "../../hooks/useGameSocket";
import { Button, Input } from "../../components/ui";

interface ActionInputProps {
  socket: ReturnType<typeof useGameSocket>;
}

export default function ActionInput({ socket }: ActionInputProps) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState(1);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const connected = useGameStore((s) => s.connected);

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
    <div className="border-t border-border bg-surface-container-low p-2 px-3 flex gap-2 items-end">
      <Input
        multiline
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={connected ? "描述你的行动、对话或提问..." : "正在连接服务器..."}
        disabled={!connected}
        rows={rows}
        className="leading-[1.5] min-h-9 max-h-40 py-2"
      />
      <Button
        onClick={handleSend}
        disabled={!connected || !text.trim()}
        className="h-9"
      >
        发送
      </Button>
    </div>
  );
}
