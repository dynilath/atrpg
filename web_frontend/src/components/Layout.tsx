import { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";

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
  main: {
    padding: 0,
  },
} as const;

const navItems = [
  { label: "首页", path: "/" },
  { label: "玩家", path: "/player" },
  { label: "编辑器", path: "/editor" },
  { label: "控制台", path: "/console" },
];

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();

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
      </header>
      <main style={styles.main}>{children}</main>
    </div>
  );
}
