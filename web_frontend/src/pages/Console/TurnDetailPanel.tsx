import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";

interface ToolCallItem {
  id: string;
  type: string;
  function: { name: string; arguments: string };
}

interface MessageItem {
  role: string;
  content: string;
  tool_calls?: ToolCallItem[];
  tool_call_id?: string;
}

interface TurnDetail {
  id: string;
  turn_no: number;
  parent_id: string | null;
  parent_turn_no: number | null;
  messages: MessageItem[];
}

interface TurnDetailPanelProps {
  turnId: string;
  turns?: Array<{ id: string; turn_no: number; usage: Record<string, number> }>;
  onBranchCreated?: () => void;
  isCurrent?: boolean;
}

function fmtUsage(usage?: Record<string, number>): string {
  if (!usage) return "";
  const prompt = usage.prompt_tokens || 0;
  const completion = usage.completion_tokens || 0;
  const cached = usage.cached_tokens || 0;
  const total = prompt + completion;
  const rate = prompt > 0 && cached > 0
    ? `，缓存命中率 ${(cached / prompt * 100).toFixed(1)}%`
    : "";
  return `词元：${(total / 1000).toFixed(1)}k  输入 ${(prompt / 1000).toFixed(1)}k  缓存 ${(cached / 1000).toFixed(1)}k  输出 ${(completion / 1000).toFixed(1)}k${rate}`;
}

function renderToolArgs(args: string): string {
  try {
    const obj = JSON.parse(args);
    return Object.entries(obj)
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(", ");
  } catch {
    return args;
  }
}

export default function TurnDetailPanel({ turnId, turns, onBranchCreated, isCurrent }: TurnDetailPanelProps) {
  const [detail, setDetail] = useState<TurnDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [branching, setBranching] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDone(false);
    apiGet<TurnDetail>(`/api/sessions/${turnId}`)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [turnId]);

  const handleBranch = async () => {
    if (branching || done) return;
    setBranching(true);
    try {
      const name = `从 #${String(detail?.turn_no ?? "?").padStart(3, "0")} 分支`;
      const res: any = await apiPost("/api/sessions/branch", { from_node_id: turnId, name });
      // 切换到新分支
      await apiPost("/api/sessions/branch/switch", { branch_id: res.branch_id });
      setDone(true);
      onBranchCreated?.();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBranching(false);
    }
  };

  if (loading) return <div className="p-8 text-muted-foreground text-center">加载中...</div>;
  if (error) return <div className="p-8 text-error text-center">{error}</div>;
  if (!detail) return <div className="p-8 text-muted-foreground text-center">轮次不存在</div>;

  const turnMeta = turns?.find((t) => t.id === turnId);
  const usageStr = fmtUsage(turnMeta?.usage);

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <h2 className="font-heading text-h3 text-primary">
            #{String(detail.turn_no).padStart(3, "0")}
          </h2>
          <span className="text-xs text-muted-foreground">
            ← {detail.parent_turn_no ? `#${String(detail.parent_turn_no).padStart(3, "0")}` : "根节点"}
          </span>
        </div>
        {isCurrent ? (
          <span className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-white">
            当前位置
          </span>
        ) : (
          <button
            onClick={handleBranch}
            disabled={branching || done}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              done
                ? "bg-success-container text-success cursor-default"
                : "bg-primary text-white hover:bg-primary-hover disabled:opacity-40"
            }`}
          >
            {done ? "✓ 已设为当前" : branching ? "处理中..." : "从此轮继续"}
          </button>
        )}
      </div>
      {usageStr && (
        <div className="text-xs text-muted-foreground font-mono mb-4">
          {usageStr}
        </div>
      )}

      <div className="space-y-3">
        {detail.messages
          .filter((m) => m.role !== "system")
          .map((m, i) => {
            if (m.role === "assistant" && m.tool_calls?.length) {
              return (
                <div key={i} className="rounded-lg p-3 chat-bg-assistant border-l-[3px] border-l-success">
                  <div className="text-caption font-semibold text-muted-foreground mb-1">主持人</div>
                  {m.content && (
                    <pre className="text-sm whitespace-pre-wrap font-body text-fg leading-relaxed mb-2">
                      {m.content}
                    </pre>
                  )}
                  {m.tool_calls.map((tc) => (
                    <div key={tc.id} className="mt-2 p-2 bg-surface-dim rounded border border-border">
                      <div className="text-caption font-semibold text-warning mb-1">
                        🔧 {tc.function.name}
                      </div>
                      <pre className="text-xs whitespace-pre-wrap font-mono text-muted-foreground">
                        {renderToolArgs(tc.function.arguments)}
                      </pre>
                    </div>
                  ))}
                </div>
              );
            }

            return (
              <div
                key={i}
                className={`rounded-lg p-3 border-l-[3px] ${
                  m.role === "user"
                    ? "bg-primary-container border-l-primary"
                    : m.role === "assistant"
                    ? "chat-bg-assistant border-l-success"
                    : "bg-surface-dim border-l-border text-xs text-muted-foreground font-mono"
                }`}
              >
                <div className="text-caption font-semibold text-muted-foreground mb-1">
                  {m.role === "user" ? "玩家" : m.role === "assistant" ? "主持人" : `工具 ${m.tool_call_id ? "→ " + m.tool_call_id.slice(-6) : ""}`}
                </div>
                <pre className="text-sm whitespace-pre-wrap font-body text-fg leading-relaxed">
                  {typeof m.content === "string" ? m.content : JSON.stringify(m.content, null, 2)}
                </pre>
              </div>
            );
          })}
      </div>
    </div>
  );
}
