/** 玩家界面的主布局 — 聊天区 + 侧边面板。 */

import { useEffect, useState, useCallback } from "react";
import { useGameStore } from "../../store/gameStore";
import { useGameSocket } from "../../hooks/useGameSocket";
import { useUserStore } from "../../store/userStore";
import ChatWindow from "./ChatWindow";
import ActionInput from "./ActionInput";
import ScenePanel from "./ScenePanel";
import CharacterCard from "./CharacterCard";

interface PlayerPageProps {
  socket: ReturnType<typeof useGameSocket>;
  bindCharacter: (characterSlug: string | null) => Promise<void>;
}

interface CharacterOption {
  slug: string;
  name: string;
  identity: string;
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
  bindSection: {
    padding: "12px",
    borderBottom: "1px solid #0f3460",
  },
  bindLabel: {
    fontSize: 11,
    color: "#8a8a9a",
    marginBottom: 6,
  },
  select: {
    width: "100%",
    padding: "6px 8px",
    fontSize: 12,
    background: "#0a0a1a",
    color: "#e0e0e0",
    border: "1px solid #0f3460",
    borderRadius: 4,
    marginBottom: 6,
  },
  bindBtn: {
    width: "100%",
    padding: "6px 0",
    fontSize: 12,
    background: "#e94560",
    color: "#fff",
    border: "none",
    borderRadius: 4,
    cursor: "pointer",
  },
  unbindBtn: {
    width: "100%",
    padding: "6px 0",
    fontSize: 12,
    background: "transparent",
    color: "#e94560",
    border: "1px solid #e94560",
    borderRadius: 4,
    cursor: "pointer",
    marginTop: 4,
  },
  bindStatus: {
    fontSize: 11,
    color: "#53c0a0",
    textAlign: "center" as const,
    padding: "4px 0",
  },
};

export default function PlayerPage({ socket, bindCharacter }: PlayerPageProps) {
  const connected = useGameStore((s) => s.connected);
  const sessionKey = useGameStore((s) => s.sessionKey);
  const user = useUserStore((s) => s.user);

  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [selectedChar, setSelectedChar] = useState<string>("");
  const [loadingChars, setLoadingChars] = useState(false);

  const currentCharSlug = user?.character_slug || null;

  // 加载可选角色列表
  useEffect(() => {
    const loadChars = async () => {
      setLoadingChars(true);
      try {
        const r = await fetch("/api/data/characters");
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        // 后端直接返回数组，也可能返回 { characters: [...] }
        const list = Array.isArray(data) ? data : (data.characters || []);
        const chars: CharacterOption[] = list.map(
          (c: { slug: string; meta: Record<string, unknown> }) => ({
            slug: c.slug,
            name: c.meta["姓名"] || c.meta["名称"] || c.slug,
            identity: c.meta["身份"] || "",
          })
        );
        setCharacters(chars);
      } catch {
        // ignore
      } finally {
        setLoadingChars(false);
      }
    };
    loadChars();
  }, []);

  const handleBind = useCallback(async () => {
    if (selectedChar) {
      await bindCharacter(selectedChar);
    }
  }, [selectedChar, bindCharacter]);

  const handleUnbind = useCallback(async () => {
    await bindCharacter(null);
  }, [bindCharacter]);

  return (
    <div style={styles.container}>
      {/* 聊天区 */}
      <div style={styles.chatArea}>
        <div style={styles.connectBar}>
          <span
            style={{
              ...styles.dot,
              background: connected ? "#53c0a0" : "#e94560",
            }}
          />
          {connected ? `已连接: ${sessionKey}` : "未连接"}
        </div>
        <ChatWindow />
        <ActionInput socket={socket} />
      </div>

      {/* 侧边面板 */}
      <div style={styles.sidebar}>
        {/* 角色绑定 */}
        <div style={styles.sidebarTitle}>角色绑定</div>
        <div style={styles.bindSection}>
          {loadingChars ? (
            <div style={{ fontSize: 11, color: "#666" }}>加载中...</div>
          ) : (
            <>
              <div style={styles.bindLabel}>
                {currentCharSlug
                  ? `当前绑定: ${currentCharSlug}`
                  : "选择要绑定的角色（可多人绑定同一角色）"}
              </div>
              <select
                style={styles.select}
                value={selectedChar}
                onChange={(e) => setSelectedChar(e.target.value)}
              >
                <option value="">-- 选择角色 --</option>
                {characters.map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.name} {c.identity ? `(${c.identity})` : ""}
                  </option>
                ))}
              </select>
              <button style={styles.bindBtn} onClick={handleBind} disabled={!selectedChar}>
                绑定角色
              </button>
              {currentCharSlug && (
                <button style={styles.unbindBtn} onClick={handleUnbind}>
                  解除绑定
                </button>
              )}
            </>
          )}
        </div>

        <div style={styles.sidebarTitle}>角色</div>
        <CharacterCard />
        <div style={styles.sidebarTitle}>场景</div>
        <ScenePanel />
      </div>
    </div>
  );
}