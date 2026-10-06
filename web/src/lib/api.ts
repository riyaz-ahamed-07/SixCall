export type DocSummary = {
  doc_id: string;
  title?: string;
  filename?: string;
  source_name?: string;
  page_count?: number;
  [key: string]: unknown;
};

export type AskAnswer = {
  text: string;
  status: "ok" | "insufficient_information";
  pages_used: number[];
  tool_trace: ToolTraceStep[];
  calls_used: number;
  question_id: string;
  reason?: string | null;
  status_reason?: string | null;
  quotes: Quote[];
  intent?: string | null;
  strategy?: string | null;
};

export type ToolTraceStep = {
  call_index?: number;
  tool?: string;
  args?: Record<string, unknown>;
  result_summary?: string;
  error?: string | null;
};

export type Quote = {
  page?: number;
  text?: string;
  id?: string;
};

export type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  answer?: AskAnswer;
};

export type AuthUser = {
  id: string;
  email: string;
};

export type AuthResponse = {
  token: string;
  expires_at: string;
  user: AuthUser;
};

/** Hit the API directly — Next rewrites drop long /ask runs with socket hang up. */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

/** Default client timeout for document Q&A (ms). Must exceed server REQUEST_DEADLINE_SEC. */
const REQUEST_TIMEOUT_MS = Number(
  process.env.NEXT_PUBLIC_API_TIMEOUT_MS ?? 120_000,
);

function storedToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("sixcall_token");
  } catch {
    return null;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  token?: string | null,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const headers = new Headers(init?.headers);
  const auth = token === undefined ? storedToken() : token;
  if (auth) headers.set("Authorization", `Bearer ${auth}`);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const parentSignal = init?.signal;
  if (parentSignal) {
    if (parentSignal.aborted) controller.abort();
    else
      parentSignal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      const label = path.includes("/ingest")
        ? "Upload timed out — large PDFs can take 1–2 minutes (parse + DB save). Retry, or keep the doc if it already appears in the list."
        : "Request timed out — try a shorter question or retry";
      throw new Error(label);
    }
    throw new Error(
      "Cannot reach API at http://127.0.0.1:8000. Start it with: uvicorn app.server:app --port 8000",
    );
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* keep raw */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export function health() {
  return request<{ status: string; db: boolean; documents: number }>("/health");
}

export function listDocuments() {
  return request<DocSummary[]>("/documents");
}

export function deleteDocument(docId: string) {
  return request<{ deleted: string }>(`/documents/${docId}`, {
    method: "DELETE",
  });
}

export type DocPreview = {
  doc_id: string;
  title: string;
  source_name?: string | null;
  page_count: number;
  page_number: number;
  page_text: string;
  headings: Array<{
    title: string;
    level: number;
    start: number;
    end: number;
  }>;
};

export function fetchDocumentPreview(docId: string, page = 1) {
  const q = new URLSearchParams({ page: String(Math.max(1, page)) });
  return request<DocPreview>(
    `/documents/${encodeURIComponent(docId)}/preview?${q}`,
  );
}

export async function fetchDocumentPdfBlob(docId: string): Promise<Blob> {
  const auth = storedToken();
  const headers = new Headers();
  if (auth) headers.set("Authorization", `Bearer ${auth}`);
  const res = await fetch(
    `${API_BASE}/documents/${encodeURIComponent(docId)}/file`,
    { headers },
  );
  if (!res.ok) {
    let detail = await res.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      /* keep */
    }
    throw new Error(detail || `PDF unavailable (${res.status})`);
  }
  return res.blob();
}

export function clearDocuments() {
  return request<{ deleted: number }>("/documents", { method: "DELETE" });
}

export async function ingestPdf(file: File) {
  const body = new FormData();
  body.append("file", file);
  // Judging textbooks (600+ pages) need several minutes for pymupdf4llm.
  return request<{ doc_id: string; filename: string }>(
    "/ingest",
    {
      method: "POST",
      body,
    },
    undefined,
    600_000,
  );
}

export function askQuestion(
  docId: string,
  question: string,
  history: Array<{
    role: "user" | "assistant";
    text: string;
    quotes?: Quote[];
    status?: AskAnswer["status"];
  }> = [],
) {
  return request<AskAnswer>(
    "/ask",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: docId,
        question,
        history: history.slice(-12).map((turn) => ({
          role: turn.role,
          text: turn.text,
          ...(turn.quotes?.length ? { quotes: turn.quotes } : {}),
          ...(turn.status ? { status: turn.status } : {}),
        })),
      }),
    },
    undefined,
    REQUEST_TIMEOUT_MS,
  );
}

export function overviewDocument(
  docId: string,
  question?: string,
  opts?: { light?: boolean },
) {
  return request<AskAnswer>("/overview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      doc_id: docId,
      ...(question ? { question } : {}),
      ...(opts?.light ? { light: true } : {}),
    }),
  });
}

export function getTrace(questionId: string) {
  return request<ToolTraceStep[]>(`/trace/${encodeURIComponent(questionId)}`);
}

export function signup(email: string, password: string) {
  return request<AuthResponse>(
    "/auth/signup",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    },
    null,
  );
}

export function login(email: string, password: string) {
  return request<AuthResponse>(
    "/auth/login",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    },
    null,
  );
}

export function logout(token: string) {
  return request<{ status: string }>("/auth/logout", { method: "POST" }, token);
}

export function me(token: string) {
  return request<{ user: AuthUser }>("/auth/me", undefined, token);
}
