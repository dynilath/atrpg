/** 角色卡侧边面板 — 从 API 读取角色数据。 */

import { useEffect, useState } from "react";
import { useUserStore } from "../../store/userStore";
import { Card, Tooltip } from "../../components/ui";

interface CharData {
  name: string;
  identity: string;
  scene_slug: string | null;
}

interface CharacterCardProps {
  onUnbind?: () => void;
}

export default function CharacterCard({ onUnbind }: CharacterCardProps) {
  const charSlug = useUserStore((s) => s.user?.character_slug ?? null);
  const [char, setChar] = useState<CharData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!charSlug) { setChar(null); return; }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/data/characters/${charSlug}`)
      .then((r) => { if (!r.ok) throw new Error("not found"); return r.json(); })
      .then((data) => {
        if (cancelled) return;
        setChar({
          name: data.meta?.name || data.meta?.title || charSlug,
          identity: data.meta?.brief || data.meta?.identity || "",
          scene_slug: data.meta?.current_location || null,
        });
      })
      .catch(() => { if (!cancelled) setChar(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [charSlug]);

  if (loading) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">加载中...</div>;
  }

  if (!char) {
    return null;
  }

  return (
    <div className="p-2">
      <Card variant="flat" className="overflow-visible">
        <div className="flex items-start justify-between">
          <div className="text-primary font-bold text-sm">{char.name}</div>
          {onUnbind && (
            <Tooltip text="解除绑定">
              <button
                onClick={onUnbind}
                className="text-muted-foreground hover:text-error text-sm leading-none ml-2 shrink-0 opacity-50 hover:opacity-100 transition-opacity"
              >
                ✕
              </button>
            </Tooltip>
          )}
        </div>
        <div className="text-muted-foreground text-caption mb-1">{char.identity}</div>
        <div className="text-[11px] opacity-70">
          {char.scene_slug ? `当前: ${char.scene_slug}` : "位置未知"}
        </div>
      </Card>
    </div>
  );
}
