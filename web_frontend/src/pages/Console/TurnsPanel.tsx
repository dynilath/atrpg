import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";

interface Turn {
  turn_no: number;
  timestamp: string;
  sender: string;
  player_text: string;
  reply_preview: string;
  usage: Record<string, number>;
}

interface TurnsPanelProps {
  sessionId: string;
}

export default function TurnsPanel({ sessionId }: TurnsPanelProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [usage, setUsage] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiGet<Turn[]>(`/api/sessions/${sessionId}/turns`),
      apiGet<Record<string, number>>(`/api/sessions/${sessionId}/usage`),
    ])
      .then(([t, u]) => {
        setTurns(t);
        setUsage(u);
      })
      .catch((e) => setError(e.message));
  }, [sessionId]);

  if (error) {
    return (
      <div style={{ padding: "var(--space-3)", color: "var(--color-error)", fontSize: 12 }}>
        {error}
      </div>
    );
  }

  const hitRate =
    usage && usage.prompt_tokens > 0
      ? ((usage.cached_tokens / usage.prompt_tokens) * 100).toFixed(1)
      : "0";

  return (
    <div>
      {usage && (
        <div
          style={{
            padding: "var(--space-2) var(--space-3)",
            background: "var(--color-surface)",
            borderBottom: "1px solid var(--color-border)",
            fontSize: 11,
          }}
        >
          <div
            style={{
              color: "var(--color-primary)",
              fontWeight: 600,
              marginBottom: "var(--space-1)",
            }}
          >
            总计用量
          </div>
          <div style={{ color: "var(--color-muted-foreground)" }}>
            输入: {usage.prompt_tokens} | 输出: {usage.completion_tokens} | 缓存命中:{" "}
            {usage.cached_tokens} ({hitRate}%)
          </div>
        </div>
      )}
      {turns.length === 0 ? (
        <div
          style={{
            padding: "var(--space-5)",
            color: "var(--color-muted-foreground)",
            textAlign: "center",
          }}
        >
          暂无轮次
        </div>
      ) : (
        turns.map((t) => {
          const u = t.usage || {};
          const hasUsage = u.prompt_tokens != null && u.prompt_tokens > 0;
          const turnHitRate =
            hasUsage && u.prompt_tokens > 0
              ? ((u.cached_tokens / u.prompt_tokens) * 100).toFixed(0)
              : "0";
          return (
            <div
              key={t.turn_no}
              style={{
                padding: "var(--space-2) var(--space-3)",
                borderBottom: "1px solid var(--color-border)",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              <div>
                #{t.turn_no}{" "}
                <span className="atrpg-caption" style={{ color: "var(--color-muted-foreground)" }}>
                  {t.timestamp}
                </span>
              </div>
              <div className="atrpg-caption" style={{ color: "var(--color-muted-foreground)" }}>
                {t.sender || "未知"}
              </div>
              <div
                style={{
                  color: "var(--color-foreground)",
                  marginTop: "var(--space-1)",
                  lineHeight: 1.4,
                }}
              >
                {t.player_text.substring(0, 80)}
              </div>
              {t.reply_preview && (
                <div
                  style={{
                    color: "var(--color-success)",
                    marginTop: "var(--space-1)",
                    fontStyle: "italic",
                    fontSize: 11,
                  }}
                >
                  {t.reply_preview.substring(0, 60)}
                </div>
              )}
              {hasUsage && (
                <div className="atrpg-caption" style={{ color: "var(--color-muted-foreground)", marginTop: 2 }}>
                  {u.prompt_tokens} / {u.completion_tokens || 0} / 缓存{u.cached_tokens || 0}
                  ({turnHitRate}%)
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
