const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type Evidence = {
  source_type?: string;
  retrieval_type?: string;
  title?: string;
  section?: string;
  article?: string;
  page_label?: string;
  record_date?: string;
  version?: string;
  author?: string;
  department?: string;
  scenario?: string;
  reliability?: string;
  label?: string;
};

export type Source = {
  document_id: string;
  document_title: string;
  chunk_id: string;
  content: string;
  chapter: string | null;
  page_start: number | null;
  page_end: number | null;
  score: number | null;
  evidence: Evidence;
  metadata: Record<string, unknown>;
};

export type AgentResponse = {
  action: "note_saved" | "answered";
  message: string;
  answer: string | null;
  intent: string | null;
  document: DocumentItem | null;
  chunks_created: number | null;
  sources: Source[];
  qa_log_id: string | null;
};

export type DocumentItem = {
  id: string;
  title: string;
  doc_type: string | null;
  version: string | null;
  effective_date: string | null;
  status: string;
  original_filename: string;
  file_size: number;
  mime_type: string | null;
  document_metadata: Record<string, unknown>;
  created_at: string;
};

export type UploadDocumentInput = {
  file: File;
  title: string;
  docType: string;
  version: string;
  effectiveDate: string;
  sourceType: string;
};

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function sendAgentMessage(message: string): Promise<AgentResponse> {
  const response = await fetch(`${API_BASE_URL}/agent/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      author: "我",
      effective_date: new Date().toISOString().slice(0, 10),
    }),
  });
  return parseResponse<AgentResponse>(response);
}

export async function listDocuments(): Promise<DocumentItem[]> {
  const response = await fetch(`${API_BASE_URL}/documents`);
  return parseResponse<DocumentItem[]>(response);
}

export async function uploadDocument(input: UploadDocumentInput): Promise<DocumentItem> {
  const body = new FormData();
  body.append("file", input.file);
  if (input.title) body.append("title", input.title);
  if (input.docType) body.append("doc_type", input.docType);
  if (input.version) body.append("version", input.version);
  if (input.effectiveDate) body.append("effective_date", input.effectiveDate);
  if (input.sourceType) body.append("source_type", input.sourceType);

  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: "POST",
    body,
  });
  return parseResponse<DocumentItem>(response);
}

export async function processDocument(documentId: string): Promise<{ chunks_created: number }> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/process`, {
    method: "POST",
  });
  return parseResponse<{ chunks_created: number }>(response);
}

export async function replaceDocument(
  documentId: string,
  input: UploadDocumentInput,
): Promise<DocumentItem> {
  const body = new FormData();
  body.append("file", input.file);
  if (input.title) body.append("title", input.title);
  if (input.docType) body.append("doc_type", input.docType);
  if (input.version) body.append("version", input.version);
  if (input.effectiveDate) body.append("effective_date", input.effectiveDate);
  if (input.sourceType) body.append("source_type", input.sourceType);

  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/replace`, {
    method: "PUT",
    body,
  });
  return parseResponse<DocumentItem>(response);
}

export async function deleteDocument(documentId: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}`, {
    method: "DELETE",
  });
  return parseResponse<{ status: string }>(response);
}
