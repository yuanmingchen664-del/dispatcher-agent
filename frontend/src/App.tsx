import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Copy,
  Database,
  FileText,
  FileUp,
  Loader2,
  MessageSquareText,
  NotebookPen,
  RefreshCw,
  Send,
  Trash2,
  Upload,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  AgentResponse,
  DocumentItem,
  Source,
  deleteDocument,
  listDocuments,
  processDocument,
  replaceDocument,
  sendAgentMessage,
  uploadDocument,
} from "./api";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  action?: AgentResponse["action"];
  intent?: string | null;
  sources?: Source[];
};

function sourceTypeText(type?: string) {
  const mapping: Record<string, string> = {
    regulation: "规章",
    manual: "手册",
    experience: "经验",
    case: "案例",
    template: "模板",
    ops_spec: "运行规范",
  };
  return mapping[type ?? ""] ?? type ?? "来源";
}

function statusText(status: string) {
  const mapping: Record<string, string> = {
    uploaded: "待处理",
    processing: "处理中",
    ready: "可用",
    failed: "失败",
    archived: "归档",
  };
  return mapping[status] ?? status;
}

function intentText(intent?: string | null) {
  const mapping: Record<string, string> = {
    chapter_existence: "章节存在判断",
    chapter_content: "章节内容查询",
    outline: "目录/章节筛选",
    approach_minima_overview: "备降标准概览",
    approach_minima_calculation: "备降标准计算",
    article_lookup: "条款查询",
    rag: "知识库检索",
  };
  return intent ? mapping[intent] ?? intent : null;
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "可以直接提问，也可以用“记一下……”保存个人经验。",
    },
  ]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadVersion, setUploadVersion] = useState("");
  const [sourceType, setSourceType] = useState("manual");
  const [error, setError] = useState<string | null>(null);
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());
  const [replacingIds, setReplacingIds] = useState<Set<string>>(new Set());
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [manualManagerOpen, setManualManagerOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const readyCount = useMemo(
    () => documents.filter((document) => document.status === "ready").length,
    [documents],
  );

  async function refreshDocuments() {
    setDocumentsLoading(true);
    try {
      setDocuments(await listDocuments());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文档列表加载失败");
    } finally {
      setDocumentsLoading(false);
    }
  }

  useEffect(() => {
    void refreshDocuments();
  }, []);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading) {
      inputRef.current?.focus();
    }
  }, [loading]);

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    setInput("");
    setError(null);
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: trimmed },
    ]);
    setLoading(true);
    try {
      const response = await sendAgentMessage(trimmed);
      const content =
        response.action === "note_saved"
          ? `${response.message}，已生成 ${response.chunks_created ?? 0} 个知识片段。`
          : response.answer ?? response.message;
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content,
          action: response.action,
          intent: response.intent,
          sources: response.sources,
        },
      ]);
      if (response.action === "note_saved") {
        await refreshDocuments();
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "请求失败";
      setError(message);
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", content: message },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function handleCopyMessage(message: ChatMessage) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => {
        setCopiedMessageId((current) => (current === message.id ? null : current));
      }, 1600);
    } catch {
      setError("复制失败，请检查浏览器剪贴板权限");
    }
  }

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!selectedFile || uploading) return;

    setUploading(true);
    setError(null);
    try {
      const document = await uploadDocument({
        file: selectedFile,
        title: uploadTitle,
        docType: sourceType,
        version: uploadVersion,
        effectiveDate: "",
        sourceType,
      });
      setSelectedFile(null);
      setUploadTitle("");
      setUploadVersion("");
      await refreshDocuments();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `已上传“${document.title}”，请在知识库列表中点击处理。`,
        },
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleProcess(documentId: string) {
    setError(null);
    setProcessingIds((current) => new Set(current).add(documentId));
    setDocuments((current) =>
      current.map((document) =>
        document.id === documentId ? { ...document, status: "processing" } : document,
      ),
    );
    try {
      await processDocument(documentId);
      await refreshDocuments();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "处理失败");
      await refreshDocuments();
    } finally {
      setProcessingIds((current) => {
        const next = new Set(current);
        next.delete(documentId);
        return next;
      });
    }
  }

  async function handleReplace(document: DocumentItem, file: File | null) {
    if (!file || replacingIds.has(document.id)) return;

    setReplacingIds((current) => new Set(current).add(document.id));
    setError(null);
    try {
      const updated = await replaceDocument(document.id, {
        file,
        title: document.title,
        docType: document.doc_type ?? String(document.document_metadata.source_type ?? "manual"),
        version: document.version ?? "",
        effectiveDate: document.effective_date ?? "",
        sourceType: String(document.document_metadata.source_type ?? document.doc_type ?? "manual"),
      });
      await refreshDocuments();
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `已替换“${updated.title}”的新版本，请点击处理以更新知识库索引。`,
        },
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "替换失败");
      await refreshDocuments();
    } finally {
      setReplacingIds((current) => {
        const next = new Set(current);
        next.delete(document.id);
        return next;
      });
    }
  }

  async function handleDelete(document: DocumentItem) {
    if (deletingIds.has(document.id)) return;
    if (!window.confirm(`确定删除“${document.title}”吗？相关知识片段也会一起删除。`)) {
      return;
    }

    setDeletingIds((current) => new Set(current).add(document.id));
    setError(null);
    try {
      await deleteDocument(document.id);
      await refreshDocuments();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
      await refreshDocuments();
    } finally {
      setDeletingIds((current) => {
        const next = new Set(current);
        next.delete(document.id);
        return next;
      });
    }
  }

  return (
    <main className="appShell">
      <section className="chatPanel">
        <header className="panelHeader">
          <div>
            <p className="eyebrow">Dispatcher Agent</p>
            <h1>签派助手</h1>
          </div>
          <div className="statusPill">
            <Database size={16} />
            {readyCount} 份可用
          </div>
        </header>

        <div className="messageList">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <div className="messageIcon">
                {message.role === "user" ? <MessageSquareText size={18} /> : <BookOpen size={18} />}
              </div>
              <div className="messageBody">
                {message.role === "assistant" && (
                  <button
                    className="copyButton"
                    type="button"
                    onClick={() => void handleCopyMessage(message)}
                    title="复制回答"
                    aria-label="复制回答"
                  >
                    {copiedMessageId === message.id ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                    {copiedMessageId === message.id ? "已复制" : "复制"}
                  </button>
                )}
                {message.role === "assistant" ? (
                  <MarkdownMessage content={message.content} />
                ) : (
                  <p>{message.content}</p>
                )}
                {message.action === "note_saved" && (
                  <span className="savedBadge">
                    <CheckCircle2 size={14} />
                    已入库
                  </span>
                )}
                {message.role === "assistant" && intentText(message.intent) && (
                  <span className="intentBadge">问题类型：{intentText(message.intent)}</span>
                )}
                {message.sources && message.sources.length > 0 && (
                  <SourcesPanel sources={message.sources} />
                )}
              </div>
            </article>
          ))}
          {loading && (
            <article className="message assistant">
              <div className="messageIcon">
                <Loader2 className="spin" size={18} />
              </div>
              <div className="messageBody">
                <p>处理中...</p>
              </div>
            </article>
          )}
          <div ref={messageEndRef} />
        </div>

        <form className="composer" onSubmit={handleSend}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="问一个签派问题，或输入：记一下 关于低能见度放行：..."
            rows={3}
          />
          <button aria-label="发送" disabled={loading || !input.trim()} title="发送">
            {loading ? <Loader2 className="spin" size={20} /> : <Send size={20} />}
          </button>
        </form>
        {error && <p className="errorText">{error}</p>}
      </section>

      <aside className="sidePanel">
        <section className="manualManager">
          <div className="blockHeader">
            <div>
              <p className="eyebrow">Manual Manager</p>
              <h2>手册管理</h2>
            </div>
            <button className="iconButton" onClick={refreshDocuments} title="刷新" aria-label="刷新">
              {documentsLoading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
            </button>
          </div>

          <div className="managerStats">
            <span>{documents.length} 份手册</span>
            <span>{readyCount} 份可用</span>
          </div>

          <button
            className="managerToggle"
            type="button"
            onClick={() => setManualManagerOpen((current) => !current)}
            aria-expanded={manualManagerOpen}
          >
            {manualManagerOpen ? "收起管理" : "展开管理"}
            <ChevronDown className={manualManagerOpen ? "toggleIcon open" : "toggleIcon"} size={17} />
          </button>

          {manualManagerOpen && (
            <>
              <form className="uploadForm" onSubmit={handleUpload}>
                <label className="filePicker">
                  <FileUp size={18} />
                  <span>{selectedFile ? selectedFile.name : "选择 PDF / TXT / MD"}</span>
                  <input
                    type="file"
                    accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
                    onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                  />
                </label>
                <input
                  value={uploadTitle}
                  onChange={(event) => setUploadTitle(event.target.value)}
                  placeholder="文档标题"
                />
                <input
                  value={uploadVersion}
                  onChange={(event) => setUploadVersion(event.target.value)}
                  placeholder="版本号，如 2026-01"
                />
                <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                  <option value="manual">手册</option>
                  <option value="regulation">规章</option>
                  <option value="ops_spec">运行规范</option>
                  <option value="experience">经验</option>
                </select>
                <button className="primaryButton" disabled={!selectedFile || uploading}>
                  {uploading ? <Loader2 className="spin" size={17} /> : <Upload size={17} />}
                  上传
                </button>
              </form>

              <section className="documentsList" aria-label="文档列表">
                {documents.map((document) => (
                  <ManualItem
                    document={document}
                    isProcessing={processingIds.has(document.id) || document.status === "processing"}
                    isReplacing={replacingIds.has(document.id)}
                    isDeleting={deletingIds.has(document.id)}
                    onProcess={() => void handleProcess(document.id)}
                    onReplace={(file) => void handleReplace(document, file)}
                    onDelete={() => void handleDelete(document)}
                    key={document.id}
                  />
                ))}
                {documents.length === 0 && <p className="emptyText">还没有文档。</p>}
              </section>
            </>
          )}
        </section>
      </aside>
    </main>
  );
}

function ManualItem({
  document,
  isProcessing,
  isReplacing,
  isDeleting,
  onProcess,
  onReplace,
  onDelete,
}: {
  document: DocumentItem;
  isProcessing: boolean;
  isReplacing: boolean;
  isDeleting: boolean;
  onProcess: () => void;
  onReplace: (file: File | null) => void;
  onDelete: () => void;
}) {
  const sourceType = String(document.document_metadata.source_type ?? document.doc_type ?? "");
  const needsProcess = document.status !== "ready";

  return (
    <article className="manualItem">
      <div className="manualIcon">
        <FileText size={18} />
      </div>
      <div className="manualMain">
        <div className="manualTitleRow">
          <h3>{document.title}</h3>
          <span className={`statusBadge ${document.status}`}>{statusText(document.status)}</span>
        </div>
        <p className="manualMeta">
          {sourceTypeText(sourceType)}
          {document.version && <span> · 版本 {document.version}</span>}
          <span> · {formatFileSize(document.file_size)}</span>
        </p>
        <p className="manualFilename">{document.original_filename}</p>
        <div className="manualActions">
          {needsProcess && (
            <button className="smallButton" onClick={onProcess} disabled={isProcessing}>
              {isProcessing ? <Loader2 className="spin" size={15} /> : <NotebookPen size={15} />}
              处理
            </button>
          )}
          <label className={`smallButton secondaryButton ${isReplacing ? "disabledButton" : ""}`}>
            {isReplacing ? <Loader2 className="spin" size={15} /> : <Upload size={15} />}
            替换
            <input
              type="file"
              accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
              disabled={isReplacing}
              onChange={(event) => onReplace(event.target.files?.[0] ?? null)}
            />
          </label>
          <button className="dangerButton" onClick={onDelete} disabled={isDeleting}>
            {isDeleting ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
            删除
          </button>
        </div>
      </div>
    </article>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdownMessage">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}

function SourcesPanel({ sources }: { sources: Source[] }) {
  return (
    <details className="sourcesPanel">
      <summary>
        <span>引用 {sources.length} 条证据</span>
        <small>展开查看</small>
      </summary>
      <div className="sourcesGrid">
        {sources.map((source, index) => (
          <SourceCard source={source} index={index + 1} key={`${source.chunk_id}-${index}`} />
        ))}
      </div>
    </details>
  );
}

function SourceCard({ source, index }: { source: Source; index: number }) {
  const evidence = source.evidence ?? {};
  return (
    <details className="sourceCard">
      <summary>
        <span>{index}. {evidence.label ?? source.document_title}</span>
        <small>{sourceTypeText(evidence.source_type)}</small>
      </summary>
      <p>{source.content}</p>
    </details>
  );
}
