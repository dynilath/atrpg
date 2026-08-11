/** 简单的 Markdown 渲染组件。 */

import { useMemo } from "react";

interface MarkdownRenderProps {
  content: string;
  className?: string;
}

interface RenderedItem {
  key: number;
  element: React.ReactNode;
  type: "li" | "table" | "other";
}

function renderLine(line: string, i: number): RenderedItem {
  const trimmed = line.trim();

  // 表格行（以 | 开头或包含多个 |）
  if (_isTableRow(trimmed)) {
    const cells = trimmed
      .split("|")
      .map((c) => c.trim())
      .filter((c) => c !== "");
    return {
      key: i,
      type: "table",
      element: <>{cells}</>, // cells 作为 React fragment 子元素，由上层组装
    };
  }

  if (trimmed.startsWith("### ")) {
    return {
      key: i,
      type: "other",
      element: (
        <h3 key={i} className="text-h4 font-heading text-primary mt-3 mb-1">
          {trimmed.slice(4)}
        </h3>
      ),
    };
  }
  if (trimmed.startsWith("## ")) {
    return {
      key: i,
      type: "other",
      element: (
        <h2 key={i} className="text-h3 font-heading text-primary mt-4 mb-1.5">
          {trimmed.slice(3)}
        </h2>
      ),
    };
  }
  if (trimmed.startsWith("# ")) {
    return {
      key: i,
      type: "other",
      element: (
        <h1 key={i} className="text-h2 font-heading text-primary mt-5 mb-2">
          {trimmed.slice(2)}
        </h1>
      ),
    };
  }

  if (trimmed === "---" || trimmed === "***" || trimmed === "___") {
    return {
      key: i,
      type: "other",
      element: <hr key={i} className="border-border my-2" />,
    };
  }

  if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
    const text = trimmed.slice(2);
    const colonIdx = text.indexOf("：");
    if (colonIdx > 0) {
      const label = text.slice(0, colonIdx);
      const rest = text.slice(colonIdx + 1);
      return {
        key: i,
        type: "li",
        element: (
          <li key={i} className="my-0.5 leading-relaxed">
            <strong>{label}</strong>：{rest}
          </li>
        ),
      };
    }
    return {
      key: i,
      type: "li",
      element: (
        <li key={i} className="my-0.5 leading-relaxed">
          {text}
        </li>
      ),
    };
  }

  if (!trimmed) {
    return { key: i, type: "other", element: <br key={i} /> };
  }

  // 先转义 HTML，再套用轻量 markdown 语法（防注入：原样替换会导致存储型 XSS）
  const escaped = trimmed
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const html = escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(
      /`(.+?)`/g,
      `<code style="background:var(--color-surface-container-high-val);padding:1px 4px;border-radius:var(--radius-sm);font-size:12px;font-family:var(--font-mono);">$1</code>`
    );

  return {
    key: i,
    type: "other",
    element: (
      <p
        key={i}
        className="my-1 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    ),
  };
}

function _isTableRow(line: string): boolean {
  // 表格行：至少有一个 |，且看起来像表格（不是普通文本中的管道符）
  if (!line.includes("|")) return false;
  // 排除标题、列表、横线等
  if (line.startsWith("#") || line.startsWith("- ") || line.startsWith("* ")) return false;
  // 排除只有 --- 或 *** 的横线
  if (/^[-*_]{3,}$/.test(line)) return false;
  // 检查是否真的像表格：以 | 开头或包含多个 |
  const pipes = line.split("|").length - 1;
  return pipes >= 2 || (line.startsWith("|") && pipes >= 1);
}

export default function MarkdownRender({ content, className }: MarkdownRenderProps) {
  const lines = useMemo(() => content.split("\n"), [content]);
  const items = useMemo(() => lines.map((line, i) => renderLine(line, i)), [lines]);

  // 将连续的 <li> 包进 <ul>，连续的 table 行拼成 <table>
  const elements: React.ReactNode[] = [];
  let liBuffer: React.ReactNode[] = [];
  let tableBuffer: { key: number; cells: string[] }[] = [];

  const flushLi = () => {
    if (liBuffer.length > 0) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="list-disc pl-5 my-1">
          {liBuffer}
        </ul>
      );
      liBuffer = [];
    }
  };

  const flushTable = () => {
    if (tableBuffer.length < 2) {
      // 不够组成表格（至少需要 head + separator），降级为普通文本
      for (const row of tableBuffer) {
        elements.push(
          <p key={`t-${row.key}`} className="my-1 leading-relaxed">
            {row.cells.join(" | ")}
          </p>
        );
      }
      tableBuffer = [];
      return;
    }
    const headCells = tableBuffer[0].cells;
    const bodyRows = tableBuffer.slice(2); // skip header and separator
    elements.push(
      <div key={`tbl-${elements.length}`} className="overflow-x-auto my-2">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-surface-elevated">
              {headCells.map((c, ci) => (
                <th key={ci} className="border border-border px-3 py-1.5 text-left font-semibold">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, ri) => (
              <tr key={ri} className="even:bg-surface-elevated/50">
                {row.cells.map((c, ci) => (
                  <td key={ci} className="border border-border px-3 py-1.5">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableBuffer = [];
  };

  for (const item of items) {
    if (item.type === "li") {
      flushTable();
      liBuffer.push(item.element);
    } else if (item.type === "table") {
      flushLi();
      // item.element is a fragment containing cell strings
      const cells: string[] = [];
      // Extract cells from the fragment's children
      const fragment = item.element as React.ReactElement;
      if (fragment.props.children) {
        const children = Array.isArray(fragment.props.children) ? fragment.props.children : [fragment.props.children];
        for (const child of children) {
          if (typeof child === "string") cells.push(child);
        }
      }
      tableBuffer.push({ key: item.key, cells });
    } else {
      flushLi();
      flushTable();
      elements.push(item.element);
    }
  }
  flushLi();
  flushTable();

  return (
    <div className={`break-words font-body text-base [&_strong]:font-bold [&_em]:italic ${className || ""}`}>
      {elements}
    </div>
  );
}
