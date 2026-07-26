/** PlayerPageWrapper — 连接 WebSocket 并渲染玩家界面。 */

import { useGameSocket } from "../../hooks/useGameSocket";
import { useUserIdentity } from "../../hooks/useUserIdentity";
import PlayerPage from "./PlayerPage";

export default function PlayerPageWrapper() {
  const { userId, provider, loading, bindCharacter } = useUserIdentity();

  const socket = useGameSocket({ provider, userId });

  if (loading || !userId) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-52px)] text-muted-foreground">
        正在连接...
      </div>
    );
  }

  return <PlayerPage socket={socket} bindCharacter={bindCharacter} />;
}
