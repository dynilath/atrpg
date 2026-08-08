import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";

interface ModelProfile {
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  thinking: boolean;
  temperature?: number | null;
  max_tokens?: number | null;
  reasoning_effort?: string | null;
}

type Workflows = Record<string, string>;

// 内置工作场景（键 → 中文标签）
const WORKFLOW_DEFS: { key: string; label: string; hint: string }[] = [
  { key: "chat", label: "对话", hint: "主持人对局 / 编辑助手对话等主模型" },
  { key: "utility", label: "轻量任务", hint: "文档消化、摘要、标题生成等" },
  { key: "utility_large", label: "大上下文任务", hint: "长文档处理（可选）" },
  { key: "embedding", label: "向量嵌入", hint: "检索向量化（可选）" },
];

// 编辑任务工作场景（键 → 中文标签）
const EDITOR_WF_DEFS: { key: string; label: string }[] = [
  { key: "story_arc", label: "故事弧光" },
  { key: "character", label: "玩家角色" },
  { key: "npc", label: "NPC" },
  { key: "item", label: "物品" },
  { key: "scene", label: "情景" },
  { key: "location", label: "地点" },
  { key: "terminology", label: "设定术语" },
  { key: "state_record", label: "状态记录" },
];

interface ConfigPanelProps {
  section: "ai" | "qqbot";
}

export default function ConfigPanel({ section }: ConfigPanelProps) {
  // ---- 模型库 ----
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [workflows, setWorkflows] = useState<Workflows>({});
  const [editorWorkflows, setEditorWorkflows] = useState<Workflows>({});
  const [modelsSaved, setModelsSaved] = useState(false);
  const [wfSaved, setWfSaved] = useState(false);
  const [ewfSaved, setEwfSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // ---- 模型列表获取（下拉选择提示） ----
  const [modelOptions, setModelOptions] = useState<Record<string, string[]>>({});
  const [fetching, setFetching] = useState<Record<string, boolean>>({});

  // QQ Bot
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrStatus, setQrStatus] = useState<string>("");
  const [qrError, setQrError] = useState<string | null>(null);
  const [qrPolling, setQrPolling] = useState(false);
  const [qrInterval, setQrInterval] = useState<ReturnType<typeof setInterval> | null>(null);
  const [qqConfig, setQqConfig] = useState<{ app_id?: string; client_secret?: string }>({});

  // ---- 上下文窗口 ----
  const [ctxKeep, setCtxKeep] = useState(20);
  const [ctxSlide, setCtxSlide] = useState(5);
  const [ctxSaved, setCtxSaved] = useState(false);

  useEffect(() => {
    apiGet<{ models: ModelProfile[] }>("/api/config/models").then((d) => {
      setModels(d.models || []);
    }).catch(() => {});
    apiGet<{ workflows: Workflows }>("/api/config/workflows").then((d) => {
      setWorkflows(d.workflows || {});
    }).catch(() => {});
    apiGet<{ editor_workflows: Workflows }>("/api/config/editor-workflows").then((d) => {
      setEditorWorkflows(d.editor_workflows || {});
    }).catch(() => {});
    apiGet<Record<string, string>>("/api/config/qqbot").then(setQqConfig).catch(() => {});
    apiGet<{ window_keep?: number; window_slide?: number }>("/api/config/context").then((d) => {
      if (typeof d.window_keep === "number") setCtxKeep(d.window_keep);
      if (typeof d.window_slide === "number") setCtxSlide(d.window_slide);
    }).catch(() => {});
  }, []);

  const saveContext = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/config/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ window_keep: ctxKeep, window_slide: ctxSlide }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || await r.text());
      setCtxSaved(true);
      setTimeout(() => setCtxSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  // ---------- 模型库 ----------

  const updateModel = (idx: number, patch: Partial<ModelProfile>) => {
    setModels((list) => list.map((m, i) => (i === idx ? { ...m, ...patch } : m)));
  };

  const addModel = () => {
    const base = `model-${models.length + 1}`;
    setModels((list) => [...list, {
      name: base,
      base_url: "",
      api_key: "",
      model: "",
      thinking: false,
    }]);
  };

  const removeModel = (idx: number) => {
    setModels((list) => list.filter((_, i) => i !== idx));
  };

  const fetchModelList = async (idx: number) => {
    const m = models[idx];
    if (!m.base_url || !m.api_key) return;
    setFetching((f) => ({ ...f, [idx]: true }));
    try {
      const r = await fetch(`${m.base_url}/models`, {
        headers: { Authorization: `Bearer ${m.api_key}` },
      });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      const list = (data.data || data).map((x: any) => x.id || x.name || String(x)).filter(Boolean);
      setModelOptions((o) => ({ ...o, [idx]: list }));
    } catch (e: any) {
      setError(`获取模型列表失败: ${e.message}`);
    } finally {
      setFetching((f) => ({ ...f, [idx]: false }));
    }
  };

  const saveModels = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/config/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ models }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || await r.text());
      setModels(data.models || models);
      setModelsSaved(true);
      setTimeout(() => setModelsSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const saveWorkflows = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/config/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflows }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || await r.text());
      setWorkflows(data.workflows || workflows);
      setWfSaved(true);
      setTimeout(() => setWfSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const saveEditorWorkflows = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/config/editor-workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ editor_workflows: editorWorkflows }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || await r.text());
      setEditorWorkflows(data.editor_workflows || editorWorkflows);
      setEwfSaved(true);
      setTimeout(() => setEwfSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  // ---------- QQ Bot ----------

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

  const inputCls =
    "bg-bg border border-border rounded px-3 py-2 text-fg text-sm outline-none focus:border-primary placeholder:text-muted-foreground/50";

  return (
    <div className="p-4 space-y-6 max-w-2xl">
      {section === "ai" && (
        <section>
          <h3 className="text-h4 font-heading text-fg mb-1">模型管理</h3>
          <p className="text-xs text-muted-foreground mb-4">
            模型库与工作场景分开设置：先在模型库添加多个模型配置（含思考参数），
            再为每个工作场景选择要使用的模型。
          </p>

          {/* 模型库 */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-fg">模型库</h4>
              <button
                onClick={addModel}
                className="px-3 py-1.5 text-xs border border-border rounded-md text-muted-foreground hover:text-fg"
              >
                + 添加模型
              </button>
            </div>

            {models.length === 0 && (
              <div className="text-sm text-muted-foreground bg-surface-dim rounded-lg p-4">
                尚未添加模型。点击「+ 添加模型」创建一个配置。
              </div>
            )}

            {models.map((m, idx) => (
              <div key={idx} className="border border-border rounded-lg p-3 space-y-2 bg-surface-dim/40">
                <div className="flex gap-2 items-center">
                  <input
                    className={`${inputCls} flex-1`}
                    placeholder="配置名称（如 deepseek-main）"
                    value={m.name}
                    onChange={(e) => updateModel(idx, { name: e.target.value })}
                  />
                  <button
                    onClick={() => removeModel(idx)}
                    className="px-2 py-1 text-xs text-error border border-error/30 rounded hover:bg-error/10 shrink-0"
                  >
                    删除
                  </button>
                </div>
                <input
                  className={`${inputCls} w-full`}
                  placeholder="API 地址，如 https://api.deepseek.com"
                  value={m.base_url}
                  onChange={(e) => updateModel(idx, { base_url: e.target.value })}
                />
                <div className="flex gap-2">
                  <input
                    type="password"
                    className={`${inputCls} flex-1`}
                    placeholder={m.api_key ? "••••••••••••••••" : "API Key"}
                    value={m.api_key}
                    onChange={(e) => updateModel(idx, { api_key: e.target.value })}
                  />
                  <input
                    className={`${inputCls} flex-1`}
                    placeholder="模型 ID，如 deepseek-v4-pro"
                    value={m.model}
                    onChange={(e) => updateModel(idx, { model: e.target.value })}
                  />
                  <button
                    onClick={() => fetchModelList(idx)}
                    disabled={!m.base_url || !m.api_key}
                    className="px-3 py-2 text-xs border border-border rounded text-muted-foreground hover:text-fg disabled:opacity-30 shrink-0"
                  >
                    {fetching[idx] ? "..." : "获取列表"}
                  </button>
                </div>
                {modelOptions[idx] && modelOptions[idx].length > 0 && (
                  <div className="max-h-28 overflow-y-auto border border-border rounded bg-bg">
                    {modelOptions[idx].map((mid) => (
                      <div
                        key={mid}
                        className="px-3 py-1.5 text-sm cursor-pointer hover:bg-surface-dim text-muted-foreground hover:text-fg"
                        onClick={() => updateModel(idx, { model: mid })}
                      >
                        {mid}
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!m.thinking}
                      onChange={(e) => updateModel(idx, { thinking: e.target.checked })}
                      className="accent-primary"
                    />
                    启用思考（reasoning）
                  </label>
                  <input
                    className={`${inputCls} w-36`}
                    placeholder="temperature"
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={m.temperature ?? ""}
                    onChange={(e) =>
                      updateModel(idx, {
                        temperature: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  />
                  <input
                    className={`${inputCls} w-32`}
                    placeholder="max_tokens"
                    type="number"
                    min="1"
                    value={m.max_tokens ?? ""}
                    onChange={(e) =>
                      updateModel(idx, {
                        max_tokens: e.target.value === "" ? null : Number(e.target.value),
                      })
                    }
                  />
                  <input
                    className={`${inputCls} w-32`}
                    placeholder="reasoning_effort"
                    value={m.reasoning_effort ?? ""}
                    onChange={(e) =>
                      updateModel(idx, { reasoning_effort: e.target.value || null })
                    }
                  />
                </div>
              </div>
            ))}

            <button
              onClick={saveModels}
              disabled={saving}
              className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存模型库"}
            </button>
            {modelsSaved && <span className="text-success text-xs ml-2">已保存</span>}
          </div>

          {/* 工作场景映射 */}
          <div className="mt-8 space-y-3">
            <h4 className="text-sm font-medium text-fg">工作场景</h4>
            <p className="text-xs text-muted-foreground">
              为每个工作场景选择使用模型库中的哪个配置。
            </p>
            {WORKFLOW_DEFS.map((w) => (
              <div key={w.key} className="flex items-center gap-3">
                <div className="w-36 shrink-0">
                  <div className="text-sm text-fg">{w.label}</div>
                  <div className="text-xs text-muted-foreground">{w.hint}</div>
                </div>
                <select
                  className={`${inputCls} flex-1`}
                  value={workflows[w.key] ?? ""}
                  onChange={(e) =>
                    setWorkflows((wf) => ({ ...wf, [w.key]: e.target.value }))
                  }
                >
                  <option value="">（未设置）</option>
                  {models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} — {m.model || "（未填模型 ID）"}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <button
              onClick={saveWorkflows}
              disabled={saving}
              className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存工作场景"}
            </button>
            {wfSaved && <span className="text-success text-xs ml-2">已保存</span>}
          </div>

          {/* 编辑任务模型映射 */}
          <div className="mt-8 space-y-3">
            <h4 className="text-sm font-medium text-fg">编辑任务模型倾向</h4>
            <p className="text-xs text-muted-foreground">
              为每种编辑任务指定倾向的模型（留空则使用「对话」场景的模型）。
              例如：弧光设计可用创意性强的模型，术语定义可用轻量模型。
            </p>
            {EDITOR_WF_DEFS.map((w) => (
              <div key={w.key} className="flex items-center gap-3">
                <div className="w-24 shrink-0">
                  <div className="text-sm text-fg">{w.label}</div>
                </div>
                <select
                  className={`${inputCls} flex-1`}
                  value={editorWorkflows[w.key] ?? ""}
                  onChange={(e) =>
                    setEditorWorkflows((ewf) => ({ ...ewf, [w.key]: e.target.value }))
                  }
                >
                  <option value="">（使用对话场景模型）</option>
                  {models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} — {m.model || "（未填模型 ID）"}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <button
              onClick={saveEditorWorkflows}
              disabled={saving}
              className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存编辑任务模型"}
            </button>
            {ewfSaved && <span className="text-success text-xs ml-2">已保存</span>}
          </div>

          {/* 上下文窗口配置 */}
          <div className="mt-8 space-y-3">
            <h4 className="text-sm font-medium text-fg">上下文窗口</h4>
            <p className="text-xs text-muted-foreground">
              阶梯式滑动窗口：保留最近 N 轮对话后，每累计超出 N 轮就滑掉最早 M 轮
              （以完整轮次为边界）。滑出的旧轮内容已通过工具落盘到 data/ 文档，
              主持人可按需查询，不影响世界状态一致性。
            </p>
            <div className="flex items-center gap-4">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">保留轮数 (window_keep)</label>
                <input
                  className={`${inputCls} w-32`}
                  type="number"
                  min="1"
                  value={ctxKeep}
                  onChange={(e) => setCtxKeep(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">滑动轮数 (window_slide)</label>
                <input
                  className={`${inputCls} w-32`}
                  type="number"
                  min="1"
                  value={ctxSlide}
                  onChange={(e) => setCtxSlide(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
            </div>
            <button
              onClick={saveContext}
              disabled={saving}
              className="px-4 py-2 text-sm bg-primary text-on-primary rounded-md hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存上下文窗口"}
            </button>
            {ctxSaved && <span className="text-success text-xs ml-2">已保存</span>}
          </div>

          {error && <div className="text-error text-xs mt-3">{error}</div>}
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
              <div className="overflow-hidden rounded-lg border border-border bg-white w-fit">
                <iframe
                  src={qrUrl}
                  title="QQ Bot 官方扫码页"
                  className="w-[340px] h-[600px] block"
                  loading="eager"
                />
              </div>
              <div className="text-sm text-muted-foreground">{qrStatus}</div>
              <div className="text-sm">
                无法显示官方扫码页？可直接打开链接：
                <br />
                <a
                  href={qrUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs break-all text-primary underline"
                >
                  {qrUrl}
                </a>
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
