/** PlayerPageWrapper — 连接 WebSocket 并渲染玩家界面。 */

import { useEffect, useState } from "react";
import { useGameSocket } from "../../hooks/useGameSocket";
import PlayerPage from "./PlayerPage";

export default function PlayerPageWrapper() {
  const [sessionKey] = useState(() => `web_player_${Date.now()}`);
  const socket = useGameSocket({ sessionKey });

  useEffect(() => {
    socket.connect();
  }, [socket]);

  return <PlayerPage socket={socket} />;
}
