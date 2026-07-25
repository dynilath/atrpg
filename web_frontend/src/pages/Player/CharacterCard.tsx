/** 角色卡侧边面板 — 从 API 读取角色数据。 */

import { useEffect, useState } from "react";
import { useUserStore } from "../../store/userStore";
import { Card } from "../../components/ui";

interface CharData {
  name: string;
  identity: string;
  scene_slug: string | null;
}

export default function CharacterCard() {
  const charSlug = useUserStore((s) => s.user?.character_slug ?? null);
  const [char, setChar] = useState<CharData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!charSlug) {
      setChar(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`/api/data/characters/${charSlug}`)
      .then((r) => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setChar({
          name: data.meta?.姓名 || data.meta?.名称 || charSlug,
          identity: data.meta?.身份 || "",
          scene_slug: data.meta?.当前场景 || null,
        });
      })
      .catch(() => {
        if (!cancelled) setChar(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [charSlug]);

  if (loading) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">加载中...</div>;
  }

  if (!char) {
    return null; // 由 PlayerPage 外层处理"无角色"状态
  }

  return (
    <div className="p-2">
      <Card variant="flat">
        <div className="text-primary font-bold text-sm mb-1">{char.name}</div>
        <div className="text-muted-foreground text-caption mb-1">{char.identity}</div>
        <div className="text-[11px] opacity-70">
          {char.scene_slug ? `当前: ${char.scene_slug}` : "位置未知"}
        </div>
      </Card>
    </div>
  );
}
