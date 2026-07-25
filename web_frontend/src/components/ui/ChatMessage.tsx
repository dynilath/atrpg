import type { ReactNode } from "react";

type ChatRole = "user" | "assistant" | "system";

interface ChatMessageProps {
  role: ChatRole;
  content: ReactNode;
}

const roleLabel: Record<ChatRole, string> = {
  user: "你",
  assistant: "主持人",
  system: "系统",
};

const roleCls: Record<ChatRole, string> = {
  user: "self-end max-w-[85%] border-l-[3px] border-l-primary bg-primary-container",
  assistant:
    "self-start max-w-[85%] border-l-[3px] border-l-success chat-bg-assistant",
  system:
    "self-center max-w-[80%] border-l-[3px] border-l-error chat-bg-system",
};

export default function ChatMessage({ role, content }: ChatMessageProps) {
  const isSystem = role === "system";
  return (
    <div
      className={`flex flex-col gap-1 rounded-md px-4 ${isSystem ? "py-2" : "py-3"} ${roleCls[role]}`}
    >
      <span className="text-caption font-semibold text-muted-foreground">
        {roleLabel[role]}
      </span>
      <span
        className={`break-words whitespace-normal ${isSystem ? "text-caption text-muted-foreground" : "text-base"}`}
      >
        {content}
      </span>
    </div>
  );
}

interface ChatFlowProps {
  children: ReactNode;
  className?: string;
}

export function ChatFlow({ children, className = "" }: ChatFlowProps) {
  return (
    <div className={`flex flex-col gap-3 ${className}`.trim()}>{children}</div>
  );
}
