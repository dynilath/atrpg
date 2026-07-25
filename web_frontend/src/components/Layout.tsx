import { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useUserIdentity } from "../hooks/useUserIdentity";

const styles = {
  container: {
    fontFamily: "system-ui, sans-serif",
    background: "#1a1a2e",
    color: "#e0e0e0",
    minHeight: "100vh",
    margin: 0,
  },
  header: {
    background: "#16213e",
    padding: "10px 20px",
    borderBottom: "1px solid #0f3460",
    display: "flex",
    alignItems: "center",
    gap: 16,
  },
  title: {
    fontSize: 18,
    color: "#e94560",
    fontWeight: "bold",
    cursor: "pointer",
  } as const,
  nav: {
    display: "flex",
    gap: 12,
    fontSize: 13,
    flex: 1,
  },
  link: {
    color: "#8a8a9a",
    cursor: "pointer",
    textDecoration: "none",
    padding: "4px 8px",
    borderRadius: 4,
  },
  activeLink: {
    color: "#e0e0e0",
    background: "#0f3460",
  },
  userInfo: {
    fontSize: 12,
    color: "#8a8a9a",
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  adminBadge: {
    fontSize: 10,
    background: "#e94560",
    color: "#fff",
    padding: "1px 5px",
    borderRadius: 3,
  },
  main: {
    padding: 0,
  },
} as const;

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, loading } = useUserIdentity();

  const isAdmin = user?.is_admin ?? false;

  const navItems = [
    { label: "首页", path: "/" },
    { label: "游戏聊天", path: "/player" },
    ...(isAdmin
      ? [
          { label: "编辑器", path: "/editor" },
          { label: "控制台", path: "/console" },
        ]
      : []),
  ];

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <span style={styles.title} onClick={() => navigate("/")}>
          ATRPG
        </span>
        <nav style={styles.nav}>
          {navItems.map((item) => (
            <a
              key={item.path}
              style={{
                ...styles.link,
                ...(location.pathname === item.path ? styles.activeLink : {}),
              }}
              onClick={() => navigate(item.path)}
            >
              {item.label}
            </a>
          ))}
        </nav>
        {!loading && user && (
          <div style={styles.userInfo}>
            <span>{user.display_name}</span>
            {isAdmin && <span style={styles.adminBadge}>管理员</span>}
          </div>
        )}
      </header>
      <main style={styles.main}>{children}</main>
    </div>
  );
}