/** 备团编辑器主页面。 */

import { useState, useCallback, useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sidebar, SbTabs, SbTab, SbList, Button } from "../../components/ui";
import EditorAIPanel from "./EditorAIPanel";

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
  { key: "scenes", label: "情境" },
  { key: "locations", label: "地点" },
];

const KIND_LABELS: Record<string, string> = {
  "story-arcs": "弧光",
  characters: "玩家角色",
  npcs: "NPC",
  items: "物品",
  scenes: "情境",
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
  const [showEdit, setShowEdit] = useState(false);
  const [editMeta, setEditMeta] = useState<Record<string, string> | null>(null);
  const [editBody, setEditBody] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = useCallback(async () => {
    if (!selectedSlug || !editMeta) return;
    setSaving(true);
    try {
      const dataKind = DATA_API[activeTab];
      const r = await fetch(`/api/data/${dataKind}/${selectedSlug}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meta: editMeta, body: editBody }),
      });
      if (!r.ok) throw new Error(await r.text());
      setSelectedMeta(editMeta);
      setSelectedBody(editBody);
      setShowEdit(false);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }, [selectedSlug, editMeta, editBody, activeTab]);

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
    setShowEdit(false);
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

  const enterEdit = useCallback(() => {
    if (selectedMeta) {
      setEditMeta({ ...selectedMeta });
      setEditBody(selectedBody);
      setShowEdit(true);
    }
  }, [selectedMeta, selectedBody]);

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
            const name = doc.meta?.name || doc.meta?.名称 || doc.meta?.姓名 || doc.meta?.标题 || doc.slug;
            const desc = doc.meta?.brief || doc.meta?.级别 || doc.meta?.身份 || "";
            const isPerson = activeTab === "characters" || activeTab === "npcs";

            return (
              <div
                key={doc.slug}
                className={`px-3 py-2 cursor-pointer transition-[filter] duration-150 hover:brightness-[.97] ${
                  selectedSlug === doc.slug
                    ? "bg-primary-container text-primary"
                    : "text-fg"
                }`}
                onClick={() => loadDetail(activeTab, doc.slug)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter") loadDetail(activeTab, doc.slug);
                }}
              >
                {isPerson ? (
                  <>
                    <div className="text-sm font-medium">{name}</div>
                    {desc && (
                      <div className="text-caption text-muted-foreground text-right mt-0.5">
                        {desc}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex justify-between items-baseline gap-2">
                    <span className="text-sm font-medium min-w-0 break-all">{name}</span>
                    {desc && (
                      <span className="text-caption text-muted-foreground shrink-0">{desc}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </SbList>
      </Sidebar>

      {/* 右侧：详情 */}
      <div className="flex-1 overflow-y-auto flex flex-col">
        {selectedMeta ? (
          <>
            {/* Toolbar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-border">
              <span className="text-sm text-muted-foreground font-mono">
                {selectedSlug}
              </span>
              {showEdit ? (
                <div className="flex gap-2">
                  <Button size="sm" className="h-10" onClick={handleSave} disabled={saving}>
                    {saving ? "保存中..." : "保存"}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-10" onClick={() => setShowEdit(false)}>
                    取消
                  </Button>
                </div>
              ) : (
                <Button size="sm" className="h-10" onClick={enterEdit}>
                  手动编辑
                </Button>
              )}
            </div>

            <div className="p-4 flex-1 overflow-y-auto">
              {showEdit ? (
                /* 编辑模式 */
                <div className="space-y-3 mb-4">
                  <EditRow label="名称" value={editMeta?.name || editMeta?.名称 || editMeta?.姓名 || ""} onChange={(v) => setEditMeta((m) => ({ ...m!, name: v }))} />
                  <EditRow label="类型" value={editMeta?.type || editMeta?.类型 || ""} onChange={(v) => setEditMeta((m) => ({ ...m!, type: v }))} />
                  <EditRow label="简介" value={editMeta?.brief || editMeta?.身份 || ""} onChange={(v) => setEditMeta((m) => ({ ...m!, brief: v }))} />
                  <EditRow label="性质" value={editMeta?.nature || editMeta?.性质 || ""} onChange={(v) => setEditMeta((m) => ({ ...m!, nature: v }))} />
                  <div className="flex gap-3">
                    <span className="text-muted-foreground text-sm shrink-0 mt-2">正文：</span>
                    <textarea
                      className="flex-1 min-h-[300px] bg-bg border border-border rounded-md p-3 text-sm font-mono text-fg resize-y"
                      value={editBody}
                      onChange={(e) => setEditBody(e.target.value)}
                    />
                  </div>
                </div>
              ) : (
                /* 预览模式 */
                <>
                  <div className="mb-4 space-y-3">
                    <MetaRow label="名称" value={selectedMeta.name || selectedMeta.名称 || selectedMeta.姓名 || selectedSlug || ""} />
                    <MetaRow label="类型" value={selectedMeta.type || selectedMeta.类型 || ""} />
                    <MetaRow label="简介" value={selectedMeta.brief || selectedMeta.身份 || ""} />
                    <MetaRow label="性质" value={selectedMeta.nature || selectedMeta.性质 || ""} />
                  </div>

                  {selectedMeta.custom_info && typeof selectedMeta.custom_info === "object" && (
                    <details className="mb-4" open>
                      <summary className="text-sm text-muted-foreground cursor-pointer hover:text-fg">
                        自定义信息
                      </summary>
                      <div className="mt-2 space-y-2 pl-2 border-l-2 border-border">
                        {Object.entries(selectedMeta.custom_info as Record<string, string>).map(([k, v]) => (
                          <MetaRow key={k} label={k} value={String(v)} />
                        ))}
                      </div>
                    </details>
                  )}

                  <div className="prose prose-sm max-w-none text-fg
                    [&_h1]:text-xl [&_h1]:font-bold [&_h1]:mt-8 [&_h1]:mb-4 [&_h1]:border-b [&_h1]:border-border [&_h1]:pb-2
                    [&_h2]:text-lg [&_h2]:font-bold [&_h2]:mt-6 [&_h2]:mb-3
                    [&_h3]:text-base [&_h3]:font-bold [&_h3]:mt-4 [&_h3]:mb-2
                    [&_h4]:text-sm [&_h4]:font-bold [&_h4]:mt-3 [&_h4]:mb-1
                    [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-2
                    [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-2
                    [&_li]:my-0.5
                    [&_table]:w-full [&_table]:border-collapse [&_table]:my-3
                    [&_th]:border [&_th]:border-border [&_th]:bg-surface-dim [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-sm [&_th]:font-semibold
                    [&_td]:border [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:text-sm
                    [&_tbody>tr:nth-child(even)]:bg-surface-dim/30
                    [&_p]:my-2 [&_p]:leading-relaxed
                    [&_code]:bg-surface-dim [&_code]:px-1 [&_code]:rounded
                    [&_pre]:bg-surface-dim [&_pre]:p-3 [&_pre]:rounded-md [&_pre]:overflow-x-auto [&_pre]:my-3
                    [&_blockquote]:border-l-[3px] [&_blockquote]:border-primary [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_blockquote]:my-3
                    [&_hr]:border-border [&_hr]:my-6
                    [&_a]:text-primary [&_strong]:font-bold [&_em]:italic
                  ">
                    <Markdown remarkPlugins={[remarkGfm]}>{selectedBody || "（无正文）"}</Markdown>
                  </div>
                </>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
            <p>选择一个{KIND_LABELS[activeTab]}查看详情</p>
          </div>
        )}

      </div>
      <EditorAIPanel />
    </div>
  );
}

/** 详情行：label + value */
function MetaRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-muted-foreground shrink-0">{label}：</span>
      <span className="text-fg min-w-0 break-all">{value}</span>
    </div>
  );
}

function EditRow({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex gap-3 items-center text-sm">
      <span className="text-muted-foreground shrink-0">{label}：</span>
      <input
        className="flex-1 bg-bg border border-border rounded px-3 py-1.5 text-fg outline-none focus:border-primary"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
