interface TurnSummary {
  id: string;
  turn_no: number;
  parent_id: string | null;
  parent_turn_no: number | null;
  sender: string;
  branch_name: string;
}

interface TurnListPanelProps {
  turns: TurnSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  error: string | null;
  currentId: string | null;
}

export default function TurnListPanel({ turns, selectedId, onSelect, error, currentId }: TurnListPanelProps) {
  if (error) {
    return <div className="p-3 text-error text-xs">{error}</div>;
  }

  if (turns.length === 0) {
    return (
      <div className="p-10 text-muted-foreground text-center text-sm">
        暂无轮次
      </div>
    );
  }

  return (
    <>
      {turns.map((t) => (
        <div
          key={t.id}
          className={`relative px-3 py-2 cursor-pointer transition-[filter] duration-150 hover:brightness-[.97] ${
            selectedId === t.id
              ? "bg-primary-container text-primary"
              : "text-fg"
          }`}
          onClick={() => onSelect(t.id)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter") onSelect(t.id); }}
        >
          {/* 当前标记 — 右上角 */}
          {currentId === t.id && (
            <span className="absolute top-1 right-1 text-xs font-bold px-1.5 py-0.5 rounded-sm bg-primary text-white leading-none">
              当前
            </span>
          )}

          {/* 行1：编号 + 父节点 + 分支名 */}
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <span className="text-sm font-medium">
                #{String(t.turn_no).padStart(3, "0")}
              </span>
              <span className="text-xs text-muted-foreground">
                ← {t.parent_turn_no ? `#${String(t.parent_turn_no).padStart(3, "0")}` : "根"}
              </span>
            </span>

            {/* 分支名 — 右上角，但避让当前标记 */}
            {t.branch_name && !currentId && (
              <span className="text-xs text-muted-foreground bg-surface-dim px-1.5 py-0.5 rounded">
                {t.branch_name}
              </span>
            )}
          </div>

          {/* 行2：发送者 + 分支名（当与当前冲突时降到此处） */}
          <div className="flex items-center justify-between mt-0.5">
            <span className="text-xs text-muted-foreground truncate">{t.sender || "系统"}</span>
            {t.branch_name && currentId && (
              <span className="text-xs text-muted-foreground bg-surface-dim px-1.5 py-0.5 rounded shrink-0 ml-2">
                {t.branch_name}
              </span>
            )}
          </div>
        </div>
      ))}
    </>
  );
}
