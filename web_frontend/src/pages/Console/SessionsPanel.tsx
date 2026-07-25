interface SessionsPanelProps {
  sessions: string[];
  selected: string | null;
  onSelect: (sid: string) => void;
  error: string | null;
}

export default function SessionsPanel({
  sessions,
  selected,
  onSelect,
  error,
}: SessionsPanelProps) {
  if (error) {
    return (
      <div style={{ padding: 12, color: "#e94560", fontSize: 12 }}>
        {error}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div style={{ padding: 40, color: "#555", textAlign: "center", fontSize: 14 }}>
        暂无会话
      </div>
    );
  }

  return (
    <>
      {sessions.map((sid) => (
        <div
          key={sid}
          onClick={() => onSelect(sid)}
          style={{
            padding: "8px 12px",
            cursor: "pointer",
            borderBottom: "1px solid #0f3460",
            fontSize: 12,
            background: selected === sid ? "#0f3460" : "transparent",
          }}
        >
          {sid}
        </div>
      ))}
    </>
  );
}
