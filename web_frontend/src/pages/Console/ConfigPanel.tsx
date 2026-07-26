import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";

interface AIConfig {
  model: string;
  endpoint: string;
  api_key: string;
}

interface ConfigPanelProps {
  section: "ai" | "qqbot";
}

export default function ConfigPanel({ section }: ConfigPanelProps) {
  const [aiConfig, setAiConfig] = useState<AIConfig | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiSaving, setAiSaving] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [showFullForm, setShowFullForm] = useState(false);

  // QQ Bot
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrStatus, setQrStatus] = useState<string>("");
  const [qrError, setQrError] = useState<string | null>(null);
  const [qrPolling, setQrPolling] = useState(false);
  const [qrInterval, setQrInterval] = useState<ReturnType<typeof setInterval> | null>(null);
  const [qqConfig, setQqConfig] = useState<{ app_id?: string; client_secret?: string }>({});

  useEffect(() => {
    apiGet<AIConfig>("/api/config/ai").then((c) => {
      setAiConfig(c);
      if (c.endpoint && c.api_key) fetchModels(c.endpoint, c.api_key);
    }).catch(() => {});
    apiGet<Record<string, string>>("/api/config/qqbot").then(setQqConfig).catch(() => {});
  }, []);

  const fetchModels = async (endpoint: string, apiKey: string) => {
    setModelsLoading(true);
    try {
      const r = await fetch(`${endpoint}/models`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      const list = (data.data || data).map((m: any) => m.id || m.name || String(m)).filter(Boolean);
      setModels(list);
    } catch {
      setModels([]);
    } finally {
      setModelsLoading(false);
    }
  };

  const saveAi = async () => {
    if (!aiConfig) return;
    setAiSaving(true);
    try {
      const r = await fetch("/api/config/ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(aiConfig),
      });
      if (!r.ok) throw new Error(await r.text());
      setAiError(null);
      setShowFullForm(false);
    } catch (e: any) {
      setAiError(e.message);
    } finally {
      setAiSaving(false);
    }
  };

  const startQr = async () => {
    setQrError(null);
    setQrStatus("正在生成二维码...");
    try {
      const r = await fetch("/api/config/qqbot/qr/start", { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setQrUrl(data.qr_url);
      setQrStatus("请在手机QQ中扫描二维码");

      const interval = setInterval(async () => {
        try {
          const sr = await fetch("/api/config/qqbot/qr/status");
          const sd = await sr.json();
          if (sd.status === "completed") {
            setQrStatus("绑定成功！");
            setQrPolling(false);
            setQqConfig({ app_id: sd.app_id, client_secret: "***" });
            clearInterval(interval);
          } else if (sd.status === "expired") {
            setQrStatus("二维码已过期");
            setQrError("请刷新重试");
            setQrPolling(false);
            clearInterval(interval);
          }
        } catch {}
      }, 2000);
      setQrInterval(interval);
      setQrPolling(true);
    } catch (e: any) {
      setQrError(e.message);
    }
  };

  const cancelQr = () => {
    if (qrInterval) clearInterval(qrInterval);
    setQrPolling(false);
    setQrUrl(null);
    setQrStatus("");
  };

  return (
    <div className="p-4 space-y-6 max-w-xl">
      {section === "ai" && (
        <section>
          <h3 className="text-h4 font-heading text-fg mb-3">AI 接口配置</h3>

          {/* 已配置摘要 */}
          {aiConfig?.endpoint && !showFullForm ? (
            <div className="space-y-3">
              <div className="bg-surface-dim rounded-lg p-4 space-y-2">
                <div className="flex gap-2 text-sm">
                  <span className="text-muted-foreground shrink-0">API 地址：</span>
                  <code className="text-fg">{aiConfig.endpoint}</code>
                </div>
                <div className="flex gap-2 text-sm">
                  <span className="text-muted-foreground shrink-0">API Key：</span>
                  <span className="text-muted-foreground">{"•".repeat(16)}</span>
                </div>
                <div className="flex gap-2 text-sm">
                  <span className="text-muted-foreground shrink-0">模型：</span>
                  <span className="text-fg font-medium">{aiConfig.model || "（未设置）"}</span>
                </div>
              </div>
              <button
                onClick={() => setShowFullForm(true)}
                className="px-4 py-2 text-sm border border-border rounded-md hover:bg-surface-dim"
              >
                修改配置
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">API 地址</span>
                <input
                  placeholder=""
                  className="bg-bg border border-border rounded px-3 py-2 text-fg text-sm outline-none focus:border-primary"
                  value={aiConfig?.endpoint || ""}
                  onChange={(e) => setAiConfig((c) => ({ ...c!, endpoint: e.target.value }))}
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">API Key</span>
                <input
                  type="password"
                  placeholder={aiConfig?.api_key ? "••••••••••••••••" : ""}
                  className="bg-bg border border-border rounded px-3 py-2 text-fg text-sm outline-none focus:border-primary placeholder:text-muted-foreground/50"
                  value={aiConfig?.api_key || ""}
                  onChange={(e) => setAiConfig((c) => ({ ...c!, api_key: e.target.value }))}
                />
              </label>

              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">模型</span>
                <div className="flex gap-2">
                  <input
                    className="flex-1 bg-bg border border-border rounded px-3 py-2 text-fg text-sm outline-none focus:border-primary"
                    value={aiConfig?.model || ""}
                    onChange={(e) => setAiConfig((c) => ({ ...c!, model: e.target.value }))}
                    placeholder="deepseek-chat"
                  />
                  <button
                    onClick={() => {
                      if (aiConfig?.endpoint && aiConfig?.api_key) {
                        fetchModels(aiConfig.endpoint, aiConfig.api_key);
                      }
                    }}
                    disabled={!aiConfig?.endpoint || !aiConfig?.api_key}
                    className="px-3 py-2 text-xs border border-border rounded text-muted-foreground hover:text-fg disabled:opacity-30 shrink-0"
                  >
                    {modelsLoading ? "..." : "获取列表"}
                  </button>
                </div>
                {models.length > 0 && (
                  <div className="mt-1 max-h-32 overflow-y-auto border border-border rounded bg-bg">
                    {models.map((m) => (
                      <div
                        key={m}
                        className="px-3 py-1.5 text-sm cursor-pointer hover:bg-surface-dim text-muted-foreground hover:text-fg"
                        onClick={() => setAiConfig((c) => ({ ...c!, model: m }))}
                      >
                        {m}
                      </div>
                    ))}
                  </div>
                )}
              </label>

              <div className="flex gap-2">
                <button
                  onClick={saveAi}
                  disabled={aiSaving}
                  className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-50"
                >
                  {aiSaving ? "保存中..." : "保存"}
                </button>
                {showFullForm && aiConfig?.endpoint && (
                  <button
                    onClick={() => setShowFullForm(false)}
                    className="px-4 py-2 text-sm border border-border rounded-md text-muted-foreground hover:text-fg"
                  >
                    取消
                  </button>
                )}
              </div>
              {aiError && <div className="text-error text-xs">{aiError}</div>}
            </div>
          )}
        </section>
      )}

      {section === "qqbot" && (
        <section>
          <h3 className="text-h4 font-heading text-fg mb-3">QQ Bot 连接</h3>

          {qqConfig.app_id && !qrUrl ? (
            <div className="space-y-3">
              <div className="bg-surface-dim rounded-lg p-4 space-y-2">
                <div className="flex gap-2 text-sm">
                  <span className="text-muted-foreground shrink-0">状态：</span>
                  <span className="text-success font-medium">已连接</span>
                </div>
                <div className="flex gap-2 text-sm">
                  <span className="text-muted-foreground shrink-0">App ID：</span>
                  <code className="text-fg">{qqConfig.app_id}</code>
                </div>
              </div>
              <button
                onClick={startQr}
                className="px-4 py-2 text-sm border border-border rounded-md hover:bg-surface-dim"
              >
                重新扫码绑定
              </button>
            </div>
          ) : qrUrl ? (
            <div className="space-y-3">
              <div className="bg-white p-2 rounded-md inline-block">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(qrUrl)}`}
                  alt="QQ Bot QR Code"
                  className="w-48 h-48"
                />
              </div>
              <div className="text-sm text-muted-foreground">{qrStatus}</div>
              <div className="text-sm">
                或打开链接：<br />
                <code className="text-xs break-all text-muted-foreground">{qrUrl}</code>
              </div>
              {qrPolling && (
                <button
                  onClick={cancelQr}
                  className="px-3 py-1.5 text-sm border border-border rounded-md text-muted-foreground hover:text-fg"
                >
                  取消
                </button>
              )}
            </div>
          ) : (
            <button
              onClick={startQr}
              className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover"
            >
              扫码绑定 QQ Bot
            </button>
          )}
          {qrError && <div className="text-error text-xs mt-2">{qrError}</div>}
        </section>
      )}
    </div>
  );
}
