/** 场景信息侧边面板。 */

import { useGameStore } from "../../store/gameStore";

export default function ScenePanel() {
  const scene = useGameStore((s) => s.scene);

  if (!scene) {
    return (
      <div
        style={{
          padding: "12px 16px",
          fontSize: 12,
          color: "#666",
        }}
      >
        暂无场景信息
      </div>
    );
  }

  return (
    <div style={{ padding: "8px 12px", fontSize: 12 }}>
      <div
        style={{
          color: "#53c0a0",
          fontWeight: "bold",
          fontSize: 14,
          marginBottom: 6,
        }}
      >
        {scene.name}
      </div>
      <p style={{ color: "#a0a0b0", lineHeight: 1.5, marginBottom: 8 }}>
        {scene.description.substring(0, 150)}
        {scene.description.length > 150 ? "..." : ""}
      </p>
      {scene.attendees.length > 0 && (
        <div>
          <div style={{ color: "#8a8a9a", fontSize: 11, marginBottom: 4 }}>
            在场者
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {scene.attendees.map((a) => (
              <span
                key={a}
                style={{
                  background: "#0f3460",
                  color: "#c0c0d0",
                  padding: "2px 8px",
                  borderRadius: 10,
                  fontSize: 11,
                }}
              >
                {a}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
