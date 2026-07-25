import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import SessionsPanel from "./SessionsPanel";
import TurnsPanel from "./TurnsPanel";

export default function ConsolePage() {
  const [sessions, setSessions] = useState<string[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<string[]>("/api/sessions")
      .then(setSessions)
      .catch((e) => setError(e.message));
  }, []);

  const styles = {
    container: {
      display: "flex",
      height: "calc(100vh - 48px)",
      overflow: "hidden",
    },
    sidebar: {
      width: 380,
      borderRight: "1px solid #0f3460",
      overflowY: "auto" as const,
      background: "#16213e",
    },
    detail: {
      flex: 1,
      overflowY: "auto" as const,
      padding: 16,
    },
  };

  return (
    <div style={styles.container}>
      <div style={styles.sidebar}>
        <div
          style={{
            padding: "8px 12px",
            fontSize: 13,
            color: "#8a8a9a",
            textTransform: "uppercase",
            borderBottom: "1px solid #0f3460",
            position: "sticky" as const,
            top: 0,
            background: "#16213e",
            zIndex: 1,
          }}
        >
          会话
        </div>
        <SessionsPanel
          sessions={sessions}
          selected={selectedSession}
          onSelect={setSelectedSession}
          error={error}
        />
        <div
          style={{
            padding: "8px 12px",
            fontSize: 13,
            color: "#8a8a9a",
            textTransform: "uppercase",
            borderBottom: "1px solid #0f3460",
            borderTop: "1px solid #0f3460",
            position: "sticky" as const,
            top: 0,
            background: "#16213e",
            zIndex: 1,
          }}
        >
          轮次
        </div>
        {selectedSession && <TurnsPanel sessionId={selectedSession} />}
      </div>
      <div style={styles.detail}>
        <p style={{ color: "#555", textAlign: "center", paddingTop: 40 }}>
          请选择轮次查看详情
        </p>
      </div>
    </div>
  );
}
