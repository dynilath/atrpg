import type { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useUserIdentity } from "../hooks/useUserIdentity";
import type { Permission } from "../store/userStore";
import { Navigation } from "./ui";

interface LayoutProps {
  children: ReactNode;
}

const permissionNav: Record<Permission, { key: string; label: string; path: string }[]> = {
  "玩家": [
    { key: "home", label: "首页", path: "/" },
    { key: "player", label: "游戏聊天", path: "/player" },
  ],
  "主持人": [
    { key: "home", label: "首页", path: "/" },
    { key: "player", label: "游戏聊天", path: "/player" },
    { key: "editor", label: "编辑器", path: "/editor" },
  ],
  "管理员": [
    { key: "home", label: "首页", path: "/" },
    { key: "player", label: "游戏聊天", path: "/player" },
    { key: "editor", label: "编辑器", path: "/editor" },
    { key: "console", label: "控制台", path: "/console" },
  ],
};

const permissionBadge: Record<Permission, { label: string; className: string }> = {
  "玩家": { label: "玩家", className: "text-[10px] bg-surface-container-high text-fg px-1 py-px rounded-sm" },
  "主持人": { label: "主持人", className: "text-[10px] bg-primary-container text-primary px-1 py-px rounded-sm" },
  "管理员": { label: "管理员", className: "text-[10px] bg-primary text-on-primary px-1 py-px rounded-sm" },
};

export default function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, loading } = useUserIdentity();

  const permission = user?.permission ?? "玩家";
  const navItems = permissionNav[permission] || permissionNav["玩家"];
  const badge = permissionBadge[permission];

  return (
    <div className="min-h-screen flex flex-col">
      <Navigation
        brand="ATRPG"
        items={navItems.map((item) => ({
          key: item.key,
          label: item.label,
          active: location.pathname === item.path,
          onClick: () => navigate(item.path),
        }))}
        user={
          !loading && user ? (
            <>
              <span className="atrpg-caption text-fg font-mono">
                {user.id}
              </span>
              <span className={badge.className}>{badge.label}</span>
            </>
          ) : undefined
        }
      />
      <main className="flex-1 flex flex-col">{children}</main>
    </div>
  );
}
