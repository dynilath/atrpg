/** 角色创建对话框 — AI 辅助生成角色卡。 */

import { useState } from "react";
import { Button, Input } from "../../components/ui";
import ChatMessage from "../../components/ui/ChatMessage";

interface CharacterCreateDialogProps {
  onCreated: (slug: string) => void;
  onClose: () => void;
}

interface StepMsg {
  role: "user" | "assistant" | "system";
  content: string;
}

export default function CharacterCreateDialog({ onCreated, onClose }: CharacterCreateDialogProps) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState<StepMsg[]>([]);
  const [result, setResult] = useState<{ slug: string; name: string; body: string } | null>(null);

  const handleGenerate = async () => {
    const text = prompt.trim();
    if (!text || loading) return;

    setSteps([{ role: "user", content: text }]);
    setPrompt("");
    setLoading(true);

    try {
      const r = await fetch("/api/editor/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, type: "pc" }),
      });
      const data = await r.json();

      if (data.ok) {
        setResult({ slug: data.slug, name: data.title || data.slug, body: data.body || "" });
        setSteps((prev) => [
          ...prev,
          { role: "assistant", content: `已生成角色「${data.title || data.slug}」` },
        ]);
      } else {
        setSteps((prev) => [
          ...prev,
          { role: "system", content: `生成失败: ${data.error || "未知错误"}` },
        ]);
      }
    } catch (e: any) {
      setSteps((prev) => [
        ...prev,
        { role: "system", content: `请求失败: ${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!result) return;
    await onCreated(result.slug);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-surface border border-border rounded-xl shadow-modal w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <h2 className="font-heading text-h4 font-heading text-fg">创建角色</h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-fg text-lg leading-none px-1"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-[200px]">
          {steps.length === 0 && !result && (
            <p className="text-muted-foreground text-sm text-center py-8">
              描述你想创建的角色概念，AI 将为你生成完整角色卡
            </p>
          )}

          {steps.map((s, i) => (
            <ChatMessage key={i} role={s.role} content={s.content} />
          ))}

          {result && (
            <div className="mt-2 border border-border rounded-lg p-4 bg-surface-dim">
              <h3 className="font-heading text-h4 text-primary mb-2">{result.name}</h3>
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-body leading-relaxed max-h-[200px] overflow-y-auto">
                {result.body}
              </pre>
              <div className="flex gap-2 mt-3">
                <Button variant="primary" size="sm" onClick={handleConfirm}>
                  确认创建并绑定
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setResult(null)}>
                  重新生成
                </Button>
              </div>
            </div>
          )}

          {loading && (
            <div className="text-muted-foreground text-sm text-center py-4">
              AI 正在生成角色...
            </div>
          )}
        </div>

        {/* Footer — input */}
        {!result && (
          <div className="border-t border-border p-3 flex gap-2">
            <Input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleGenerate();
                }
              }}
              placeholder="例如：一个退役的侦察兵，擅长潜行和观察，性格谨慎但讲义气"
              disabled={loading}
              className="flex-1 min-w-0 w-auto"
            />
            <Button onClick={handleGenerate} disabled={loading || !prompt.trim()} size="sm">
              {loading ? "生成中..." : "生成"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
