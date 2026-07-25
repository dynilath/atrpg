/** 备团编辑器主页面。 */

import { useState, useCallback, useEffect } from "react";
import EditorChat from "./EditorChat";

type ResourceKind = "story-arcs" | "characters" | "npcs" | "items" | "scenes" | "locations";

interface ResourceDoc {
  slug: string;
  meta: Record<string, string>;
}

const TABS: { key: ResourceKind; label: string }[] = [
  { key: "story-arcs", label: "📜 弧光" },
  { key: "characters", label: "🧑 玩家角色" },
  { key: "npcs", label: "👤 NPC" },
  { key: "items", label: "📦 物品" },
  { key: "scenes", label: "🎬 场景" },
  { key: "locations", label: "📍 地点" },
];

const KIND_LABELS: Record<string, string> = {
  "story-arcs": "弧光",
  characters: "玩家角色",
  npcs: "NPC",
  items: "物品",
  scenes: "场景",
  locations: "地点",
};

/** 前端 kind → 编辑器列表 API 路径段 */
const EDITOR_API: Record<string, string> = {
  "story-arcs": "arcs",
  characters: "characters",
  npcs: "characters",
  items: "items",
  scenes: "scenes",
  locations: "locations",
};

/** 前端 kind → 数据 API 路径段（详情读取） */
const DATA_API: Record<string, string> = {
  "story-arcs": "story-arcs",
  characters: "characters",
  npcs: "npcs",
  items: "items",
  scenes: "scenes",
  locations: "locations",
};

export default function EditorPage() {
  const [activeTab, setActiveTab] = useState<ResourceKind>("story-arcs");
  const [resources, setResources] = useState<ResourceDoc[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [selectedMeta, setSelectedMeta] = useState<Record<string, string> | null>(null);
  const [selectedBody, setSelectedBody] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);

  const loadList = useCallback(async (kind: ResourceKind) => {
    setLoading(true);
    setError(null);
    setSelectedSlug(null);
    setSelectedMeta(null);
    setSelectedBody("");
    try {
      const apiPath = EDITOR_API[kind];
      const r = await fetch(`/api/editor/${apiPath}`);
      if (!r.ok) throw new Error(await r.text());
      let data = await r.json();
      // characters endpoint returns {characters, npcs} — 按当前 Tab 分离
      if (apiPath === "characters" && data.characters) {
        data = kind === "npcs"
          ? (data.npcs || [])
          : (data.characters || []);
      }
      setResources(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(
    async (kind: ResourceKind, slug: string) => {
      setSelectedSlug(slug);
      setSelectedBody("");
      setSelectedMeta(null);
      try {
        const dataKind = DATA_API[kind];
        const r = await fetch(`/api/data/${dataKind}/${slug}`);
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        setSelectedMeta(data.meta);
        setSelectedBody(data.body || "");
      } catch (e: any) {
        setError(e.message);
      }
    },
    []
  );

  // Load list on mount and tab switch
  useEffect(() => { loadList(activeTab); }, [activeTab, loadList]);

  const handleTabChange = (tab: ResourceKind) => {
    setActiveTab(tab);
    loadList(tab);
  };

  const styles = {
    container: {
      display: "flex",
      height: "calc(100vh - 48px)",
      overflow: "hidden",
    },
    sidebar: {
      width: 320,
      borderRight: "1px solid #0f3460",
      background: "#16213e",
      display: "flex",
      flexDirection: "column" as const,
    },
    tabs: {
      display: "flex",
      flexWrap: "wrap" as const,
      gap: 0,
      borderBottom: "1px solid #0f3460",
      padding: "4px 4px 0",
    },
    tab: {
      padding: "6px 10px",
      fontSize: 12,
      cursor: "pointer",
      borderRadius: "4px 4px 0 0",
      borderWidth: 0,
      background: "transparent",
      color: "#8a8a9a",
      whiteSpace: "nowrap" as const,
    },
    activeTab: {
      background: "#1a1a2e",
      color: "#e94560",
      borderBottom: "2px solid #e94560",
    },
    list: {
      flex: 1,
      overflowY: "auto" as const,
    },
    listItem: {
      padding: "8px 12px",
      fontSize: 12,
      cursor: "pointer",
      borderBottom: "1px solid #0f3460",
      color: "#c0c0d0",
    },
    activeItem: {
      background: "#0f3460",
      borderLeft: "3px solid #e94560",
    },
    detail: {
      flex: 1,
      overflowY: "auto" as const,
      padding: 16,
      display: "flex",
      flexDirection: "column" as const,
    },
    metaTag: {
      display: "inline-block",
      background: "#0f3460",
      color: "#8a8a9a",
      padding: "2px 6px",
      borderRadius: 4,
      fontSize: 11,
      marginRight: 4,
    },
    chatButton: {
      background: "#e94560",
      color: "#fff",
      border: "none",
      borderRadius: 6,
      padding: "8px 16px",
      fontSize: 13,
      cursor: "pointer",
      marginTop: 12,
    },
  };

  return (
    <div style={styles.container}>
      {/* 左侧：资源列表 */}
      <div style={styles.sidebar}>
        <div style={styles.tabs}>
          {TABS.map((t) => (
            <button
              key={t.key}
              style={{
                ...styles.tab,
                ...(activeTab === t.key ? styles.activeTab : {}),
              }}
              onClick={() => handleTabChange(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div style={styles.list}>
          {loading && <div style={{ padding: 20, color: "#555" }}>加载中...</div>}
          {error && <div style={{ padding: 12, color: "#e94560" }}>{error}</div>}
          {!loading && !error && resources.length === 0 && (
            <div style={{ padding: 20, color: "#555", textAlign: "center" }}>
              暂无{KIND_LABELS[activeTab]}
              <div style={{ fontSize: 11, color: "#666", marginTop: 8 }}>
                点击下方按钮用 AI 创建
              </div>
            </div>
          )}
          {resources.map((doc) => {
            const name = doc.meta?.名称 || doc.meta?.姓名 || doc.meta?.标题 || doc.slug;
            const extra = doc.meta?.级别 || doc.meta?.身份 || "";
            return (
              <div
                key={doc.slug}
                style={{
                  ...styles.listItem,
                  ...(selectedSlug === doc.slug ? styles.activeItem : {}),
                }}
                onClick={() => loadDetail(activeTab, doc.slug)}
              >
                <div>{name}</div>
                {extra && (
                  <div style={{ fontSize: 11, color: "#6080a0", marginTop: 2 }}>
                    {extra}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 右侧：详情 + AI 聊天 */}
      <div style={styles.detail}>
        {selectedMeta ? (
          <>
            <div style={{ marginBottom: 12 }}>
              <h2 style={{ color: "#e94560", fontSize: 18, margin: "0 0 8px" }}>
                {selectedMeta?.名称 || selectedMeta?.姓名 || selectedSlug}
              </h2>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {Object.entries(selectedMeta)
                  .filter(([k]) => !["名称", "姓名", "slug", "updated", "body"].includes(k))
                  .map(([k, v]) => (
                    <span key={k} style={styles.metaTag}>
                      {k}: {String(v).substring(0, 40)}
                    </span>
                  ))}
              </div>
            </div>
            <pre
              style={{
                flex: 1,
                background: "#0a0a1a",
                color: "#c0c0d0",
                padding: 12,
                borderRadius: 6,
                fontSize: 12,
                lineHeight: 1.6,
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                border: "1px solid #0f3460",
              }}
            >
              {selectedBody || "(无正文)"}
            </pre>
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              color: "#555",
            }}
          >
            <p style={{ marginBottom: 16 }}>
              选择一个{KIND_LABELS[activeTab]}查看详情，或通过 AI 创建新素材
            </p>
          </div>
        )}

        <button
          style={styles.chatButton}
          onClick={() => setShowChat(!showChat)}
        >
          {showChat ? "关闭 AI 助手" : `🤖 AI 辅助创建${KIND_LABELS[activeTab]}`}
        </button>

        {showChat && (
          <EditorChat
            kind={activeTab}
            onCreated={(slug) => {
              loadList(activeTab);
              setSelectedSlug(slug);
              loadDetail(activeTab, slug);
            }}
          />
        )}
      </div>
    </div>
  );
}
