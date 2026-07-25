/** 角色卡侧边面板。 */

import { useGameStore } from "../../store/gameStore";

export default function CharacterCard() {
  const character = useGameStore((s) => s.character);

  if (!character) {
    return (
      <div
        style={{
          padding: "12px 16px",
          fontSize: 12,
          color: "#666",
        }}
      >
        暂无绑定角色
        <div style={{ fontSize: 11, color: "#555", marginTop: 4 }}>
          在聊天中描述你的角色创建概念
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "8px 12px", fontSize: 12 }}>
      <div
        style={{
          color: "#4a9eff",
          fontWeight: "bold",
          fontSize: 14,
          marginBottom: 4,
        }}
      >
        {character.name}
      </div>
      <div style={{ color: "#8a8a9a", marginBottom: 6 }}>
        {character.identity}
      </div>
      <div style={{ color: "#6080a0", fontSize: 11 }}>
        {character.scene_slug
          ? `当前: ${character.scene_slug}`
          : "位置未知"}
      </div>
    </div>
  );
}
