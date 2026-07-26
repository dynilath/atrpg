/** 玩家界面主布局 — 聊天区 + 侧边面板（角色/场景）。 */

import { useEffect, useState, useCallback } from "react";
import { useGameStore } from "../../store/gameStore";
import { useGameSocket } from "../../hooks/useGameSocket";
import { useUserStore } from "../../store/userStore";
import { Sidebar, SbSection, Button } from "../../components/ui";
import ChatWindow from "./ChatWindow";
import ActionInput from "./ActionInput";
import ScenePanel from "./ScenePanel";
import CharacterCard from "./CharacterCard";
import CharacterCreateDialog from "./CharacterCreateDialog";

interface PlayerPageProps {
  socket: ReturnType<typeof useGameSocket>;
  bindCharacter: (characterSlug: string | null) => Promise<void>;
}

interface CharacterOption {
  slug: string;
  name: string;
  identity: string;
}

export default function PlayerPage({ socket, bindCharacter }: PlayerPageProps) {
  const connected = useGameStore((s) => s.connected);
  const user = useUserStore((s) => s.user);

  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [selectedChar, setSelectedChar] = useState<string>("");
  const [loadingChars, setLoadingChars] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const currentCharSlug = user?.character_slug || null;
  const hasChar = !!currentCharSlug;

  // 加载可选角色列表
  useEffect(() => {
    const loadChars = async () => {
      setLoadingChars(true);
      try {
        const r = await fetch("/api/data/characters");
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        const list = Array.isArray(data) ? data : data.characters || [];
        const chars: CharacterOption[] = list.map(
          (c: { slug: string; meta: Record<string, unknown> }) => ({
            slug: c.slug,
            name: c.meta["name"] || c.meta["姓名"] || c.meta["名称"] || c.slug,
            identity: c.meta["brief"] || c.meta["身份"] || "",
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
  }, [hasChar]); // 创建角色后重新加载列表

  const handleBind = useCallback(async () => {
    if (selectedChar) {
      await bindCharacter(selectedChar);
      setSelectedChar("");
    }
  }, [selectedChar, bindCharacter]);

  const handleUnbind = useCallback(async () => {
    await bindCharacter(null);
  }, [bindCharacter]);

  const handleCreateComplete = useCallback(async (slug: string) => {
    await bindCharacter(slug);
    setShowCreateDialog(false);
  }, [bindCharacter]);

  return (
    <div className="flex h-[calc(100vh-52px)] overflow-hidden">
      {/* 聊天区 */}
      <div className="flex-1 flex flex-col bg-bg">
        <div className="px-3 py-1.5 text-[11px] flex items-center gap-1.5 border-b border-border">
          <span
            className={`w-2 h-2 rounded-full inline-block ${connected ? "bg-success" : "bg-error"}`}
          />
          {connected ? "已连接" : "未连接"}
        </div>
        <ChatWindow />
        <ActionInput socket={socket} />
      </div>

      {/* 侧边面板 */}
      <Sidebar>
        <SbSection title="角色">
          {hasChar ? (
            <CharacterCard onUnbind={handleUnbind} />
          ) : (
            <div className="flex flex-col gap-2 px-2">
              <Button onClick={() => setShowCreateDialog(true)}>
                创建角色
              </Button>

              <div className="text-sm text-muted-foreground text-center py-1">
                或
              </div>

              {loadingChars ? (
                <div className="text-xs text-muted-foreground text-center">加载中...</div>
              ) : characters.length > 0 ? (
                <div className="flex gap-1.5 items-center">
                  <select
                    className="flex-1 px-2 py-2 text-sm bg-bg text-fg border border-border rounded-sm min-w-0"
                    value={selectedChar}
                    onChange={(e) => setSelectedChar(e.target.value)}
                  >
                    <option value="">选择已有角色</option>
                    {characters.map((c) => (
                      <option key={c.slug} value={c.slug}>
                        {c.name} {c.identity ? `(${c.identity})` : ""}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={handleBind}
                    disabled={!selectedChar}
                    className="px-3 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-45 disabled:cursor-not-allowed shrink-0"
                  >
                    绑定
                  </button>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground text-center">
                  暂无角色，请先创建
                </div>
              )}
            </div>
          )}
        </SbSection>

        <SbSection title="场景">
          <ScenePanel />
        </SbSection>
      </Sidebar>

      {/* 创建角色对话框 */}
      {showCreateDialog && (
        <CharacterCreateDialog
          onCreated={handleCreateComplete}
          onClose={() => setShowCreateDialog(false)}
        />
      )}
    </div>
  );
}
