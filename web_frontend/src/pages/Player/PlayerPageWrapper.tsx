/** PlayerPageWrapper — 连接 WebSocket 并渲染玩家界面。 */

import { useGameSocket } from "../../hooks/useGameSocket";
import { useUserIdentity } from "../../hooks/useUserIdentity";
import PlayerPage from "./PlayerPage";

export default function PlayerPageWrapper() {
  const { openid, provider, loading, bindCharacter } = useUserIdentity();

  const sessionKey = openid ? `web_player_${openid}` : "";
  // useGameSocket 会在 sessionKey 非空时自动连接，变化时自动断开旧连接
  const socket = useGameSocket({ sessionKey, provider, openid });

  if (loading || !openid) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "calc(100vh - 48px)", color: "#8a8a9a" }}>
        正在连接...
      </div>
    );
  }

  return <PlayerPage socket={socket} bindCharacter={bindCharacter} />;
}