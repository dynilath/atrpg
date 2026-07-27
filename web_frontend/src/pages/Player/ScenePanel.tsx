/** 情景信息侧边面板。 */

import { useGameStore } from "../../store/gameStore";
import { Card } from "../../components/ui";

export default function ScenePanel() {
  const scene = useGameStore((s) => s.scene);

  if (!scene) {
    return (
      <div className="px-4 py-2 text-xs text-muted-foreground">
        暂无情景信息
      </div>
    );
  }

  return (
    <div className="p-2">
      <Card variant="flat">
        <div className="text-success font-heading text-h4 mb-1">
          {scene.name}
        </div>
        <p className="atrpg-body text-muted-foreground mb-2">
          {scene.description.substring(0, 150)}
          {scene.description.length > 150 ? "..." : ""}
        </p>
        {scene.attendees.length > 0 && (
          <div>
            <span className="atrpg-eyebrow block mb-1">在场者</span>
            <div className="flex flex-wrap gap-1">
              {scene.attendees.map((a) => (
                <span
                  key={a}
                  className="bg-primary-container text-primary rounded-full px-2 py-0.5 text-caption"
                >
                  {a}
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
