/** 玩家界面的主布局 — 聊天区 + 侧边面板。 */

import { useGameStore } from "../../store/gameStore";
import { useGameSocket } from "../../hooks/useGameSocket";
import ChatWindow from "./ChatWindow";
import ActionInput from "./ActionInput";
import ScenePanel from "./ScenePanel";
import CharacterCard from "./CharacterCard";

interface PlayerPageProps {
  socket: ReturnType<typeof useGameSocket>;
}

const styles = {
  container: {
    display: "flex",
    height: "calc(100vh - 48px)",
    overflow: "hidden",
  },
  chatArea: {
    flex: 1,
    display: "flex",
    flexDirection: "column" as const,
    background: "#1a1a2e",
  },
  sidebar: {
    width: 320,
    borderLeft: "1px solid #0f3460",
    background: "#16213e",
    overflowY: "auto" as const,
    display: "flex",
    flexDirection: "column" as const,
    gap: 0,
  },
  sidebarTitle: {
    padding: "10px 12px",
    fontSize: 13,
    color: "#8a8a9a",
    textTransform: "uppercase" as const,
    borderBottom: "1px solid #0f3460",
  },
  connectBar: {
    padding: "6px 12px",
    fontSize: 11,
    display: "flex",
    alignItems: "center",
    gap: 6,
    borderBottom: "1px solid #0f3460",
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    display: "inline-block",
  },
};

export default function PlayerPage({ socket }: PlayerPageProps) {
  const connected = useGameStore((s) => s.connected);
  const sessionKey = useGameStore((s) => s.sessionKey);

  return (
    <div style={styles.container}>
      {/* 聊天区 */}
      <div style={styles.chatArea}>
        <div style={styles.connectBar}>
          <span style={{ ...styles.dot, background: connected ? "#53c0a0" : "#e94560" }} />
          {connected ? `已连接: ${sessionKey}` : "未连接"}
        </div>
        <ChatWindow />
        <ActionInput socket={socket} />
      </div>

      {/* 侧边面板 */}
      <div style={styles.sidebar}>
        <div style={styles.sidebarTitle}>角色</div>
        <CharacterCard />
        <div style={styles.sidebarTitle}>场景</div>
        <ScenePanel />
      </div>
    </div>
  );
}
