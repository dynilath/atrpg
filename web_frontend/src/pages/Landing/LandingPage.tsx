interface LandingPageProps {
  onEnterConsole: () => void;
}

const cardStyle = {
  flex: "1 1 200px",
  maxWidth: 280,
  minWidth: 200,
  padding: "24px 20px",
  borderRadius: 8,
  background: "#16213e",
  border: "1px solid #0f3460",
  cursor: "pointer",
  textAlign: "center" as const,
  transition: "border-color 0.2s, transform 0.2s",
};

const features = [
  {
    key: "gm",
    title: "🎭 GM 控制台",
    desc: "管理游戏会话、角色、场景和故事线",
    action: "onEnterConsole" as const,
  },
  {
    key: "play",
    title: "🎮 玩家入口",
    desc: "加入游戏、查看角色状态、提交行动",
    action: null,
  },
  {
    key: "observe",
    title: "👀 观众模式",
    desc: "实时观看游戏进程和聊天",
    action: null,
  },
] as const;

export default function LandingPage({ onEnterConsole }: LandingPageProps) {
  const handlers: Record<string, (() => void) | undefined> = {
    onEnterConsole,
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "calc(100vh - 160px)",
        padding: "40px 20px",
      }}
    >
      <div style={{ textAlign: "center", marginBottom: 48 }}>
        <h1 style={{ fontSize: 36, color: "#e94560", margin: "0 0 12px 0" }}>
          ATRPG
        </h1>
        <p style={{ fontSize: 16, color: "#8a8a9a", margin: 0 }}>
          AI-driven Tabletop Role-Playing Game
        </p>
      </div>

      <div
        style={{
          display: "flex",
          gap: 20,
          flexWrap: "wrap",
          justifyContent: "center",
        }}
      >
        {features.map((f) => (
          <div
            key={f.key}
            style={cardStyle}
            onClick={() => {
              if (f.action) {
                const h = handlers[f.action];
                h?.();
              }
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = "#e94560";
              e.currentTarget.style.transform = "translateY(-2px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = "#0f3460";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <div style={{ fontSize: 24, marginBottom: 12 }}>{f.title}</div>
            <div style={{ fontSize: 13, color: "#8a8a9a", lineHeight: 1.5 }}>
              {f.desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
