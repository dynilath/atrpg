/** 简单的 Markdown 渲染组件。 */

import { useMemo } from "react";

interface MarkdownRenderProps {
  content: string;
  className?: string;
}

function renderLine(line: string, i: number) {
  const trimmed = line.trim();

  // 标题
  if (trimmed.startsWith("### ")) {
    return <h3 key={i} style={{ margin: "12px 0 4px", color: "#e94560", fontSize: 14 }}>{trimmed.slice(4)}</h3>;
  }
  if (trimmed.startsWith("## ")) {
    return <h2 key={i} style={{ margin: "16px 0 6px", color: "#e94560", fontSize: 16 }}>{trimmed.slice(3)}</h2>;
  }
  if (trimmed.startsWith("# ")) {
    return <h1 key={i} style={{ margin: "20px 0 8px", color: "#e94560", fontSize: 18 }}>{trimmed.slice(2)}</h1>;
  }

  // 无序列表
  if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
    const text = trimmed.slice(2);
    const colonIdx = text.indexOf("：");
    if (colonIdx > 0) {
      const label = text.slice(0, colonIdx);
      const rest = text.slice(colonIdx + 1);
      return (
        <li key={i} style={{ margin: "2px 0", lineHeight: 1.5 }}>
          <strong style={{ color: "#53c0a0" }}>{label}</strong>：{rest}
        </li>
      );
    }
    return <li key={i} style={{ margin: "2px 0", lineHeight: 1.5 }}>{text}</li>;
  }

  // 空行
  if (!trimmed) return <br key={i} />;

  // 普通段落（行内加粗/斜体）
  const html = trimmed
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code style='background:#2a2a4e;padding:1px 4px;border-radius:3px;font-size:12px;'>$1</code>");

  return (
    <p
      key={i}
      style={{ margin: "4px 0", lineHeight: 1.6 }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function MarkdownRender({ content, className }: MarkdownRenderProps) {
  const lines = useMemo(() => content.split("\n"), [content]);
  return (
    <div className={className} style={{ wordBreak: "break-word" }}>
      {lines.map((line, i) => renderLine(line, i))}
    </div>
  );
}
