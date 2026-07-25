import { ReactNode } from "react";

type Page = "landing" | "console";

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

interface LayoutProps {
  children: ReactNode;
  currentPage?: Page;
  onNavigate?: (page: Page) => void;
}

export default function Layout({ children, currentPage, onNavigate }: LayoutProps) {
  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <span style={styles.title} onClick={() => onNavigate?.("landing")}>
          ATRPG
        </span>
        <nav style={styles.nav}>
          <a
            style={{
              ...styles.link,
              ...(currentPage === "landing" ? styles.activeLink : {}),
            }}
            onClick={() => onNavigate?.("landing")}
          >
            首页
          </a>
          <a
            style={{
              ...styles.link,
              ...(currentPage === "console" ? styles.activeLink : {}),
            }}
            onClick={() => onNavigate?.("console")}
          >
            控制台
          </a>
        </nav>
      </header>
      <main style={styles.main}>{children}</main>
    </div>
  );
}
