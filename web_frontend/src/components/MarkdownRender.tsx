/** 简单的 Markdown 渲染组件。 */

import { useMemo } from "react";

interface MarkdownRenderProps {
  content: string;
  className?: string;
}

function renderLine(line: string, i: number) {
  const trimmed = line.trim();

  if (trimmed.startsWith("### ")) {
    return (
      <h3 key={i} className="text-h4 font-heading text-primary mt-3 mb-1">
        {trimmed.slice(4)}
      </h3>
    );
  }
  if (trimmed.startsWith("## ")) {
    return (
      <h2 key={i} className="text-h3 font-heading text-primary mt-4 mb-1.5">
        {trimmed.slice(3)}
      </h2>
    );
  }
  if (trimmed.startsWith("# ")) {
    return (
      <h1 key={i} className="text-h2 font-heading text-primary mt-5 mb-2">
        {trimmed.slice(2)}
      </h1>
    );
  }

  if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
    const text = trimmed.slice(2);
    const colonIdx = text.indexOf("：");
    if (colonIdx > 0) {
      const label = text.slice(0, colonIdx);
      const rest = text.slice(colonIdx + 1);
      return (
        <li key={i} className="my-0.5 leading-relaxed">
          <strong className="text-success">{label}</strong>：{rest}
        </li>
      );
    }
    return (
      <li key={i} className="my-0.5 leading-relaxed">
        {text}
      </li>
    );
  }

  if (!trimmed) return <br key={i} />;

  const html = trimmed
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(
      /`(.+?)`/g,
      `<code style="background:var(--color-surface-container-high-val);padding:1px 4px;border-radius:var(--radius-sm);font-size:12px;font-family:var(--font-mono);">$1</code>`
    );

  return (
    <p
      key={i}
      className="my-1 leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function MarkdownRender({ content, className }: MarkdownRenderProps) {
  const lines = useMemo(() => content.split("\n"), [content]);
  return (
    <div className={`break-words font-body text-base ${className || ""}`}>
      {lines.map((line, i) => renderLine(line, i))}
    </div>
  );
}
