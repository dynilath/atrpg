interface TurnSummary {
  id: string;
  turn_no: number;
  sender: string;
  branch_name: string;
}

interface TurnListPanelProps {
  turns: TurnSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  error: string | null;
}

export default function TurnListPanel({ turns, selectedId, onSelect, error }: TurnListPanelProps) {
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
          className={`px-3 py-2 cursor-pointer transition-[filter] duration-150 hover:brightness-[.97] ${
            selectedId === t.id
              ? "bg-primary-container text-primary"
              : "text-fg"
          }`}
          onClick={() => onSelect(t.id)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter") onSelect(t.id); }}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              #{String(t.turn_no).padStart(3, "0")}
            </span>
            {t.branch_name && (
              <span className="text-[10px] text-muted-foreground bg-surface-dim px-1 rounded">
                {t.branch_name}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 truncate">
            {t.sender || "系统"}
          </div>
        </div>
      ))}
    </>
  );
}
