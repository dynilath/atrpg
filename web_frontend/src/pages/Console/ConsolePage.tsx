import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import { Sidebar, SbSection } from "../../components/ui";
import TurnListPanel from "./TurnListPanel";
import TurnDetailPanel from "./TurnDetailPanel";
import ConfigPanel from "./ConfigPanel";

interface TurnSummary {
  id: string;
  turn_no: number;
  parent_id: string | null;
  parent_turn_no: number | null;
  sender: string;
  player_text: string;
  reply_preview: string;
  usage: Record<string, number>;
  llm_calls: number;
  total_msgs: number;
  branch_name: string;
  branch_id: string;
}

type MainTab = "sessions" | "ai" | "qqbot";

const MAIN_TABS: { key: MainTab; label: string }[] = [
  { key: "sessions", label: "轮次详情" },
  { key: "ai", label: "AI 接口配置" },
  { key: "qqbot", label: "QQ Bot 连接" },
];

export default function ConsolePage() {
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mainTab, setMainTab] = useState<MainTab>("sessions");
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const refreshTurns = () => {
    apiGet<TurnSummary[]>("/api/sessions").then(setTurns).catch(() => {});
  };

  const refreshActiveBranch = () => {
    apiGet<{ head_node_id: string | null }>("/api/sessions/branch/active")
      .then((d) => setCurrentId(d.head_node_id))
      .catch(() => {});
  };

  const handleReset = async () => {
    if (resetting) return;
    if (!window.confirm("重新开局将抛弃当前主持人上下文并开始新会话，旧轮次记录仍保留可回看。确定继续？")) return;
    setResetting(true);
    try {
      await apiPost("/api/sessions/reset", {});
      setSelectedId(null);
      refreshTurns();
      refreshActiveBranch();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setResetting(false);
    }
  };

  const scrollSidebarToBottom = () => {
    requestAnimationFrame(() => {
      const el = document.querySelector('[data-sidebar="left"]');
      if (el) el.scrollTop = el.scrollHeight;
    });
  };

  useEffect(() => {
    refreshTurns();
    apiGet<{ head_node_id: string | null }>("/api/sessions/branch/active")
      .then((d) => setCurrentId(d.head_node_id))
      .catch(() => {});

    // 防止重复连接（React StrictMode 会双挂载）
    if (wsRef.current) return;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/ws/console`);
    wsRef.current = ws;
    ws.onopen = () => console.log("控制台 WS 已连接");
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "new_turn") {
          refreshTurns();
          setCurrentId(msg.payload.id);
          scrollSidebarToBottom();
        }
      } catch {}
    };
    ws.onclose = () => { console.log("控制台 WS 断开"); wsRef.current = null; };
    return () => { ws.close(); wsRef.current = null; };
  }, []);

  return (
    <div className="flex h-[calc(100vh-52px)] overflow-hidden">
      {/* 左侧：主标签 + 会话列表 */}
      <Sidebar side="left" className="overflow-y-auto">
        {/* 主标签 */}
        <div className="border-b border-border">
          {MAIN_TABS.map((t) => (
            <div
              key={t.key}
              className={`px-4 py-2.5 text-sm cursor-pointer border-l-[3px] transition-colors ${
                mainTab === t.key
                  ? "border-l-primary bg-primary-container text-primary font-medium"
                  : "border-l-transparent text-muted-foreground hover:text-fg hover:bg-surface-dim"
              }`}
              onClick={() => setMainTab(t.key)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") setMainTab(t.key); }}
            >
              {t.label}
            </div>
          ))}
        </div>

        {/* 只有在轮次详情时才显示会话列表 */}
        {mainTab === "sessions" && (
          <SbSection>
            <button
              onClick={handleReset}
              disabled={resetting}
              className="w-full mb-3 px-3 py-1.5 rounded-lg text-base font-semibold transition-colors bg-error text-white hover:brightness-[.92] disabled:opacity-45 disabled:cursor-not-allowed"
            >
              {resetting ? "处理中..." : "重新开局"}
            </button>
            <div className="text-caption font-semibold text-muted-foreground uppercase tracking-[0.08em] mb-2">
              会话轮次
            </div>
            <TurnListPanel
              turns={turns}
              selectedId={selectedId}
              onSelect={setSelectedId}
              error={error}
              currentId={currentId}
            />
          </SbSection>
        )}
      </Sidebar>

      {/* 右侧 */}
      <div className="flex-1 overflow-y-auto">
        {mainTab === "sessions" ? (
          selectedId ? (
            <TurnDetailPanel turnId={selectedId} turns={turns} isCurrent={selectedId === currentId} onBranchCreated={() => {
              refreshTurns();
              refreshActiveBranch();
            }} />
          ) : (
            <p className="text-muted-foreground text-center pt-10">
              选择轮次查看详情
            </p>
          )
        ) : mainTab === "ai" ? (
          <ConfigPanel section="ai" />
        ) : (
          <ConfigPanel section="qqbot" />
        )}
      </div>
    </div>
  );
}
