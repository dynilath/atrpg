import { SbItem } from "../../components/ui";

interface SessionsPanelProps {
  sessions: string[];
  selected: string | null;
  onSelect: (sid: string) => void;
  error: string | null;
}

export default function SessionsPanel({
  sessions,
  selected,
  onSelect,
  error,
}: SessionsPanelProps) {
  if (error) {
    return (
      <div className="p-3 text-error text-xs">{error}</div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="p-10 text-muted-foreground text-center text-sm">
        暂无会话
      </div>
    );
  }

  return (
    <>
      {sessions.map((sid) => (
        <SbItem
          key={sid}
          label={sid}
          active={selected === sid}
          onClick={() => onSelect(sid)}
        />
      ))}
    </>
  );
}
