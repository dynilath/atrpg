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
      <div style={{ padding: 12, color: "#e94560", fontSize: 12 }}>
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
            padding: "8px 12px",
            background: "#0f1a2e",
            borderBottom: "1px solid #0f3460",
            fontSize: 11,
          }}
        >
          <div style={{ color: "#e94560", fontWeight: "bold", marginBottom: 4 }}>
            总计用量
          </div>
          <div style={{ color: "#6080a0" }}>
            输入: {usage.prompt_tokens} | 输出: {usage.completion_tokens} |
            缓存命中: {usage.cached_tokens} ({hitRate}%)
          </div>
        </div>
      )}
      {turns.length === 0 ? (
        <div style={{ padding: 20, color: "#555", textAlign: "center" }}>
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
                padding: "8px 12px",
                borderBottom: "1px solid #0f3460",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              <div>
                #{t.turn_no}{" "}
                <span style={{ color: "#8a8a9a" }}>{t.timestamp}</span>
              </div>
              <div style={{ color: "#8a8a9a", fontSize: 11 }}>
                {t.sender || "未知"}
              </div>
              <div style={{ color: "#c0c0d0", marginTop: 3, lineHeight: 1.4 }}>
                {t.player_text.substring(0, 80)}
              </div>
              {t.reply_preview && (
                <div
                  style={{
                    color: "#53c0a0",
                    marginTop: 2,
                    fontStyle: "italic",
                  }}
                >
                  ↳ {t.reply_preview.substring(0, 60)}
                </div>
              )}
              {hasUsage && (
                <div style={{ color: "#6080a0", fontSize: 10, marginTop: 2 }}>
                  ↓{u.prompt_tokens} ↑{u.completion_tokens || 0} 缓存
                  {u.cached_tokens || 0}({turnHitRate}%)
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
