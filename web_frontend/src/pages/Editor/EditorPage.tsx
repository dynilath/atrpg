/** 备团编辑器主页面。 */

import { useState, useCallback, useEffect } from "react";
import { Sidebar, SbTabs, SbTab, SbList, SbItem, Button } from "../../components/ui";
import EditorChat from "./EditorChat";

type ResourceKind = "story-arcs" | "characters" | "npcs" | "items" | "scenes" | "locations";

interface ResourceDoc {
  slug: string;
  meta: Record<string, string>;
}

const TABS: { key: ResourceKind; label: string }[] = [
  { key: "story-arcs", label: "弧光" },
  { key: "characters", label: "玩家角色" },
  { key: "npcs", label: "NPC" },
  { key: "items", label: "物品" },
  { key: "scenes", label: "场景" },
  { key: "locations", label: "地点" },
];

const KIND_LABELS: Record<string, string> = {
  "story-arcs": "弧光",
  characters: "玩家角色",
  npcs: "NPC",
  items: "物品",
  scenes: "场景",
  locations: "地点",
};

const EDITOR_API: Record<string, string> = {
  "story-arcs": "arcs",
  characters: "characters",
  npcs: "characters",
  items: "items",
  scenes: "scenes",
  locations: "locations",
};

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
      if (apiPath === "characters" && data.characters) {
        data = kind === "npcs" ? data.npcs || [] : data.characters || [];
      }
      setResources(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (kind: ResourceKind, slug: string) => {
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
  }, []);

  useEffect(() => {
    loadList(activeTab);
  }, [activeTab, loadList]);

  return (
    <div className="flex h-[calc(100vh-52px)] overflow-hidden">
      {/* 左侧：资源列表 */}
      <Sidebar side="left">
        <SbTabs>
          {TABS.map((t) => (
            <SbTab
              key={t.key}
              label={t.label}
              active={activeTab === t.key}
              onClick={() => setActiveTab(t.key)}
            />
          ))}
        </SbTabs>
        <SbList>
          {loading && (
            <div className="p-5 text-muted-foreground text-center">加载中...</div>
          )}
          {error && (
            <div className="p-3 text-error text-sm">{error}</div>
          )}
          {!loading && !error && resources.length === 0 && (
            <div className="p-5 text-muted-foreground text-center">
              暂无{KIND_LABELS[activeTab]}
              <div className="text-[11px] mt-2 opacity-70">
                通过 AI 助手创建
              </div>
            </div>
          )}
          {resources.map((doc) => {
            const name = doc.meta?.名称 || doc.meta?.姓名 || doc.meta?.标题 || doc.slug;
            const extra = doc.meta?.级别 || doc.meta?.身份 || "";
            return (
              <SbItem
                key={doc.slug}
                label={name}
                sub={extra || undefined}
                active={selectedSlug === doc.slug}
                onClick={() => loadDetail(activeTab, doc.slug)}
              />
            );
          })}
        </SbList>
      </Sidebar>

      {/* 右侧：详情 + AI 聊天 */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col">
        {selectedMeta ? (
          <>
            <div className="mb-3">
              <h2 className="text-primary text-h4 mb-2">
                {selectedMeta?.名称 || selectedMeta?.姓名 || selectedSlug}
              </h2>
              <div className="flex flex-wrap gap-1">
                {Object.entries(selectedMeta)
                  .filter(
                    ([k]) =>
                      !["名称", "姓名", "slug", "updated", "body"].includes(k)
                  )
                  .map(([k, v]) => (
                    <span
                      key={k}
                      className="inline-block bg-primary-container text-muted-foreground rounded-sm px-1.5 py-0.5 text-[11px]"
                    >
                      {k}: {String(v).substring(0, 40)}
                    </span>
                  ))}
              </div>
            </div>
            <pre className="flex-1 bg-bg border border-border text-fg p-3 rounded-md text-xs leading-relaxed overflow-auto whitespace-pre-wrap break-words">
              {selectedBody || "(无正文)"}
            </pre>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
            <p className="mb-4">
              选择一个{KIND_LABELS[activeTab]}查看详情，或通过 AI 创建新素材
            </p>
          </div>
        )}

        <Button
          variant="primary"
          onClick={() => setShowChat(!showChat)}
          className="mt-3"
        >
          {showChat ? "关闭 AI 助手" : `AI 辅助创建${KIND_LABELS[activeTab]}`}
        </Button>

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
