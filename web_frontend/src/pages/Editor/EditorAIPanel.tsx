import { useState, useEffect, useRef, useCallback } from "react";
import { MessageCircle, X, Send, Loader2, Paperclip, FileText, Trash2 } from "lucide-react";
import MarkdownRender from "../../components/MarkdownRender";
import { apiGet, apiPost, authHeaders } from "../../api/client";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

interface UploadedFile {
  filename: string;
  size: number;
  modified: string;
  parsed?: boolean;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export default function EditorAIPanel() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadChat = useCallback(() => {
    apiGet<{ messages: ChatMsg[] }>("/api/editor/chat")
      .then((d) => setMessages(d.messages || []))
      .catch(() => {});
  }, []);

  const loadFiles = useCallback(() => {
    apiGet<{ files: UploadedFile[] }>("/api/editor/uploads")
      .then((d) => setFiles(d.files || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (filesOpen) {
      loadChat();
      loadFiles();
    }
  }, [filesOpen, loadChat, loadFiles]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" } as ScrollIntoViewOptions);
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);
    try {
      const data = await apiPost<{ reply?: string; error?: string }>("/api/editor/chat", { message: text });
      const reply = data.reply;
      if (reply) {
        setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: `[错误] ${data.error || "未知错误"}` }]);
      }
    } catch (e: any) {
      setMessages((prev) => [...prev, { role: "assistant", content: `[网络错误] ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const doUpload = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch("/api/editor/upload", {
        method: "POST",
        headers: { ...authHeaders() },
        body: formData,
      });
      const data = await resp.json();
      if (data.ok) {
        loadFiles();
      } else {
        alert(`上传失败: ${data.error || "未知错误"}`);
      }
    } catch (e: any) {
      alert(`上传失败: ${e.message}`);
    } finally {
      setUploading(false);
    }
  }, [loadFiles]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) doUpload(f);
  }, [doUpload]);

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setDragOver(true); };
  const handleDragLeave = () => setDragOver(false);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      const ext = f.name.split(".").pop()?.toLowerCase();
      if (!ext || !["pdf", "doc", "docx"].includes(ext)) {
        alert("仅支持 PDF / DOC / DOCX 文件");
        return;
      }
      doUpload(f);
    }
  }, [doUpload]);

  const handleDeleteFile = useCallback(async (filename: string) => {
    if (!confirm(`确定要删除「${filename}」吗？`)) return;
    try {
      await fetch(`/api/editor/uploads/${encodeURIComponent(filename)}`, {
        method: "DELETE",
        headers: { ...authHeaders() },
      });
      loadFiles();
    } catch (e: any) {
      alert(`删除失败: ${e.message}`);
    }
  }, [loadFiles]);

  return (
    <>
      {/* 浮动按钮 */}
      <button
        onClick={() => setFilesOpen(!filesOpen)}
        className="fixed bottom-6 left-6 z-50 w-12 h-12 rounded-full bg-primary text-white
                   shadow-lg hover:shadow-xl hover:scale-105 active:scale-95
                   flex items-center justify-center transition-all duration-200"
        title="AI 辅助编辑"
      >
        {filesOpen ? <X size={20} /> : <MessageCircle size={20} />}
      </button>

      {/* 居中悬浮窗口 */}
      {filesOpen && (
        <>
          {/* 遮罩 */}
          <div
            className="fixed inset-0 z-40 bg-black/40"
            onClick={() => setFilesOpen(false)}
          />
          {/* 窗口 */}
          <div
            className="fixed inset-0 z-40 flex items-center justify-center pointer-events-none"
          >
            <div
              className="pointer-events-auto w-[960px] max-h-[85vh]
                          bg-surface rounded-2xl shadow-2xl border border-border
                          flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-surface-elevated shrink-0">
                <span className="font-semibold">AI 辅助编辑</span>
                <div className="flex items-center gap-3">
                  {/* 文件按钮 */}
                  <button
                    className={`text-xs px-2 py-1 rounded-md transition-colors ${
                      files.length > 0
                        ? "bg-primary/10 text-primary"
                        : "text-muted"
                    }`}
                    title={`已上传 ${files.length} 个参考文件`}
                  >
                    <Paperclip size={14} className="inline mr-1" />
                    {files.length}
                  </button>
                  <span className="text-xs text-muted">{messages.length} 条消息</span>
                  <button
                    onClick={() => setFilesOpen(false)}
                    className="text-muted-foreground hover:text-fg transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>
              </div>

              {/* 文件列表 */}
              <div className="px-5 py-2 border-b border-border bg-surface text-xs">
                {files.length === 0 ? (
                  <span className="text-muted">暂未上传参考文件 — 拖拽 PDF/DOC 到下方输入区</span>
                ) : (
                  <div className="space-y-1 max-h-24 overflow-y-auto">
                    {files.map((f) => (
                      <div key={f.filename} className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 text-muted-foreground min-w-0">
                          <FileText size={12} className="shrink-0 text-primary" />
                          <span className="truncate">{f.filename}</span>
                          <span className="text-muted shrink-0">({fmtSize(f.size)})</span>
                          {f.parsed ? (
                            <span className="text-[10px] text-primary/70 shrink-0">[已解析]</span>
                          ) : (
                            <span className="text-[10px] text-muted/50 shrink-0">[未解析]</span>
                          )}
                        </span>
                        <button
                          onClick={() => handleDeleteFile(f.filename)}
                          className="text-muted hover:text-red-500 shrink-0 transition-colors"
                          title="删除"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                {messages.length === 0 && (
                  <div className="text-center text-muted text-sm mt-24">
                    向 AI 助手提问，辅助你设计弧光、角色、NPC、物品、情景、地点、术语、状态记录等。
                    <br />
                    <span className="text-[11px]">
                      每种类型有专属设计师——直接描述需求即可自动匹配
                    </span>
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[85%] px-4 py-3 rounded-xl text-sm leading-relaxed ${
                        m.role === "user"
                          ? "bg-primary-container text-primary-on-container"
                          : "bg-surface-elevated text-foreground border border-border"
                      }`}
                    >
                      {m.role === "assistant" ? (
                        <MarkdownRender content={m.content} />
                      ) : (
                        <span>{m.content}</span>
                      )}
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-surface-elevated border border-border rounded-xl px-4 py-3 flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin text-muted" />
                      <span className="text-muted text-sm">思考中...</span>
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {/* Input + Upload */}
              <div
                className="px-4 py-3 border-t border-border bg-surface shrink-0 relative"
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                {dragOver && (
                  <div className="absolute inset-0 bg-primary/10 border-2 border-dashed border-primary rounded-b-2xl flex items-center justify-center z-10 pointer-events-none">
                    <span className="text-primary font-medium text-sm">松开以上传 PDF / DOC</span>
                  </div>
                )}
                <div className="flex gap-2">
                  {/* 上传按钮 */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.doc,.docx"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    className="shrink-0 w-10 h-10 rounded-xl border border-border
                               flex items-center justify-center
                               hover:bg-surface-elevated disabled:opacity-40 transition-colors"
                    title="上传 PDF/DOC"
                  >
                    {uploading ? (
                      <Loader2 size={16} className="animate-spin text-muted" />
                    ) : (
                      <Paperclip size={16} className="text-muted" />
                    )}
                  </button>

                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="描述你的需求...（也可拖拽 PDF/DOC 文件到此处）"
                    rows={2}
                    disabled={loading}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-border bg-surface
                               text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/30
                               placeholder:text-muted disabled:opacity-50"
                  />
                  <button
                    onClick={handleSend}
                    disabled={loading || !input.trim()}
                    className="shrink-0 w-10 h-10 rounded-xl bg-primary text-white
                               flex items-center justify-center
                               hover:bg-primary-hover disabled:opacity-40 transition-colors"
                  >
                    <Send size={16} />
                  </button>
                </div>
                <div className="text-[10px] text-muted mt-1.5 text-center">
                  支持 PDF / DOC / DOCX，最大 50MB，拖拽到此处或点击 📎 上传
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
