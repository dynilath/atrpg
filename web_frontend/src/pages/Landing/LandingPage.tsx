import { useNavigate } from "react-router-dom";
import { Card } from "../../components/ui";
import { useUserStore, type Permission } from "../../store/userStore";

interface FeatureCard {
  key: string;
  title: string;
  desc: string;
  path: string;
}

const allFeatures: Record<Permission, FeatureCard[]> = {
  "玩家": [
    { key: "play", title: "玩家入口", desc: "加入游戏、查看角色状态、提交行动", path: "/player" },
  ],
  "主持人": [
    { key: "play", title: "玩家入口", desc: "加入游戏、查看角色状态、提交行动", path: "/player" },
    { key: "editor", title: "备团编辑器", desc: "管理弧光、角色、NPC、镜头过场和物品", path: "/editor" },
  ],
  "管理员": [
    { key: "play", title: "玩家入口", desc: "加入游戏、查看角色状态、提交行动", path: "/player" },
    { key: "editor", title: "备团编辑器", desc: "管理弧光、角色、NPC、镜头过场和物品", path: "/editor" },
    { key: "console", title: "GM 控制台", desc: "查看会话历史、LLM 用量与轮次详情", path: "/console" },
  ],
};

export default function LandingPage() {
  const navigate = useNavigate();
  const user = useUserStore((s) => s.user);
  const permission = user?.permission ?? "玩家";
  const cards = allFeatures[permission] || allFeatures["玩家"];

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-5 py-8 gap-7">
      <div className="text-center">
        <h1 className="atrpg-display text-primary mb-3">ATRPG</h1>
        <p className="atrpg-lead text-muted-foreground">
          AI-driven Tabletop Role-Playing Game
        </p>
      </div>

      <div className="flex gap-5 flex-wrap justify-center max-w-[640px]">
        {cards.map((f) => (
          <Card
            key={f.key}
            variant="interactive"
            title={f.title}
            onClick={() => navigate(f.path)}
            className="max-w-[280px] min-w-[200px] text-center"
          >
            {f.desc}
          </Card>
        ))}
      </div>
    </div>
  );
}
