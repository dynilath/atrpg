import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import { Sidebar, SbSection, SbList } from "../../components/ui";
import SessionsPanel from "./SessionsPanel";
import TurnsPanel from "./TurnsPanel";

export default function ConsolePage() {
  const [sessions, setSessions] = useState<string[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<string[]>("/api/sessions")
      .then(setSessions)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="flex h-[calc(100vh-52px)] overflow-hidden">
      <Sidebar side="left" className="overflow-y-auto">
        <SbSection title="会话">
          <SessionsPanel
            sessions={sessions}
            selected={selectedSession}
            onSelect={setSelectedSession}
            error={error}
          />
        </SbSection>
        {selectedSession && (
          <SbSection title="轮次">
            <TurnsPanel sessionId={selectedSession} />
          </SbSection>
        )}
      </Sidebar>
      <div className="flex-1 overflow-y-auto p-4">
        <p className="text-muted-foreground text-center pt-10">
          请选择轮次查看详情
        </p>
      </div>
    </div>
  );
}
