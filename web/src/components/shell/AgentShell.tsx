"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import BudgetMeter from "@/components/agent/BudgetMeter";
import ContextCards from "@/components/agent/ContextCards";
import DocPreviewModal from "@/components/agent/DocPreviewModal";
import LoadingState from "@/components/agent/LoadingState";
import PromptBar from "@/components/agent/PromptBar";
import SidebarNav, { type ChatListItem } from "@/components/agent/SidebarNav";
import StreamingText, {
  type StreamingSource,
  type StreamingToken,
} from "@/components/agent/StreamingText";
import ThinkingState from "@/components/agent/ThinkingState";
import UploadProgress from "@/components/agent/UploadProgress";
import {
  askQuestion,
  deleteDocument,
  ingestPdf,
  listDocuments,
  type AskAnswer,
  type ChatTurn,
  type DocSummary,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDocName } from "@/lib/docs";

const SUGGESTIONS = [
  "Summarize the introduction",
  "Define the main concept on page 1",
  "What are the main sections?",
];

const CHATS_KEY = "sixcall.chats.v2";

type ChatSession = {
  id: string;
  title: string;
  docId: string | null;
  doc: DocSummary | null;
  turns: ChatTurn[];
  createdAt: number;
};

function tokensFromText(text: string): StreamingToken[] {
  return [{ text }];
}

function sourcesFromAnswer(answer: AskAnswer): StreamingSource[] {
  return (answer.quotes ?? []).map((quote, index) => ({
    name: `Ref ${index + 1}`,
    domain: quote.page != null ? `p.${quote.page}` : "source",
    excerpt: (quote.text ?? "").trim() || undefined,
  }));
}

function thinkingRows(answer?: AskAnswer, pending = false) {
  if (pending) {
    return [
      { primary: "Planning keywords (LLM)" },
      { primary: "Searching inverted index" },
      { primary: "Fetching pages" },
      { primary: "Writing + verifying answer (LLM)" },
    ];
  }
  if (!answer) return [];
  if (answer.strategy === "followup") {
    return [{ primary: "Follow-up (no document tools)", secondary: "0/6" }];
  }
  const rows = (answer.tool_trace ?? []).map((step) => ({
    primary: step.tool ?? "tool",
    secondary: step.result_summary?.slice(0, 36),
    mono: true,
  }));
  if (!rows.length) {
    return [{ primary: "Answered", secondary: `${answer.calls_used}/6 calls` }];
  }
  return rows;
}

function newChatId() {
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function makeEmptyChat(): ChatSession {
  return {
    id: newChatId(),
    title: "New chat",
    docId: null,
    doc: null,
    turns: [],
    createdAt: Date.now(),
  };
}

function loadChats(): { chats: ChatSession[]; activeId: string } {
  if (typeof window === "undefined") {
    const chat = makeEmptyChat();
    return { chats: [chat], activeId: chat.id };
  }
  try {
    const raw = sessionStorage.getItem(CHATS_KEY);
    if (!raw) {
      const chat = makeEmptyChat();
      return { chats: [chat], activeId: chat.id };
    }
    const parsed = JSON.parse(raw) as {
      chats?: ChatSession[];
      activeId?: string;
    };
    const chats = Array.isArray(parsed.chats) ? parsed.chats : [];
    if (!chats.length) {
      const chat = makeEmptyChat();
      return { chats: [chat], activeId: chat.id };
    }
    const activeId =
      parsed.activeId && chats.some((c) => c.id === parsed.activeId)
        ? parsed.activeId
        : chats[0].id;
    return { chats, activeId };
  } catch {
    const chat = makeEmptyChat();
    return { chats: [chat], activeId: chat.id };
  }
}

function saveChats(chats: ChatSession[], activeId: string) {
  try {
    sessionStorage.setItem(CHATS_KEY, JSON.stringify({ chats, activeId }));
  } catch {
    /* ignore quota */
  }
}

export default function AgentShell({ userEmail }: { userEmail?: string }) {
  const { logout } = useAuth();
  const router = useRouter();
  const boot = useMemo(() => loadChats(), []);
  const [chats, setChats] = useState<ChatSession[]>(boot.chats);
  const [activeChatId, setActiveChatId] = useState(boot.activeId);
  const [asking, setAsking] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const askRequestId = useRef(0);
  const askScope = useRef<{ chatId: string; docId: string } | null>(null);

  const nextTurnId = (prefix: "u" | "a") =>
    `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  const activeChat = useMemo(
    () => chats.find((c) => c.id === activeChatId) ?? chats[0] ?? null,
    [chats, activeChatId],
  );

  const activeDoc = activeChat?.doc ?? null;
  const turns = activeChat?.turns ?? [];

  const chatItems: ChatListItem[] = useMemo(
    () =>
      [...chats]
        .sort((a, b) => b.createdAt - a.createdAt)
        .map((c) => ({
          id: c.id,
          title: c.title,
          subtitle: c.doc
            ? `${c.doc.page_count ?? "?"} pages`
            : "No document yet",
          hasDoc: Boolean(c.docId),
        })),
    [chats],
  );

  /** Only the document bound to this chat — never the global library. */
  const chatDocs = useMemo(() => (activeDoc ? [activeDoc] : []), [activeDoc]);

  const lastCallsUsed = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const used = turns[i]?.answer?.calls_used;
      if (typeof used === "number") return used;
    }
    return 0;
  }, [turns]);

  const persist = useCallback(
    (nextChats: ChatSession[], nextActive: string) => {
      setChats(nextChats);
      setActiveChatId(nextActive);
      saveChats(nextChats, nextActive);
    },
    [],
  );

  const patchActiveChat = useCallback(
    (patch: Partial<ChatSession>) => {
      setChats((prev) => {
        const next = prev.map((c) =>
          c.id === activeChatId ? { ...c, ...patch } : c,
        );
        saveChats(next, activeChatId);
        return next;
      });
    },
    [activeChatId],
  );

  // Enrich active chat's doc snapshot from API (page_count / title), without
  // pulling other users' docs into this chat UI.
  useEffect(() => {
    let cancelled = false;
    const docId = activeChat?.docId;
    if (!docId) return;
    void (async () => {
      try {
        const all = await listDocuments();
        if (cancelled) return;
        const fresh = all.find((d) => d.doc_id === docId);
        if (!fresh) return;
        setChats((prev) => {
          const next = prev.map((c) =>
            c.id === activeChatId && c.docId === docId
              ? {
                  ...c,
                  doc: fresh,
                  title: formatDocName(fresh) || c.title,
                }
              : c,
          );
          saveChats(next, activeChatId);
          return next;
        });
      } catch {
        /* offline — keep local snapshot */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeChat?.docId, activeChatId]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, asking, status, activeChatId]);

  const handleNewChat = () => {
    askRequestId.current += 1;
    askScope.current = null;
    setPreviewOpen(false);
    const chat = makeEmptyChat();
    const next = [chat, ...chats];
    persist(next, chat.id);
    setError(null);
    setStatus(null);
    setAsking(false);
    setUploading(false);
    setUploadName(null);
  };

  const handlePickChat = (chatId: string) => {
    if (chatId === activeChatId) return;
    askRequestId.current += 1;
    askScope.current = null;
    setPreviewOpen(false);
    setActiveChatId(chatId);
    saveChats(chats, chatId);
    setError(null);
    setStatus(null);
    setAsking(false);
  };

  const handleDeleteChat = async (chatId: string) => {
    askRequestId.current += 1;
    askScope.current = null;
    setPreviewOpen(false);

    const target = chats.find((c) => c.id === chatId);
    const docId = target?.docId ?? null;
    const stillUsed =
      Boolean(docId) && chats.some((c) => c.id !== chatId && c.docId === docId);

    if (docId && !stillUsed) {
      setStatus("Deleting chat data…");
      try {
        await deleteDocument(docId);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Delete failed";
        if (!/404|unknown/i.test(msg)) {
          setError(msg);
          setStatus(null);
          return;
        }
      }
    }

    const remaining = chats.filter((c) => c.id !== chatId);
    const nextChats = remaining.length ? remaining : [makeEmptyChat()];
    const nextActive =
      chatId === activeChatId
        ? nextChats[0].id
        : nextChats.some((c) => c.id === activeChatId)
          ? activeChatId
          : nextChats[0].id;
    persist(nextChats, nextActive);
    setError(null);
    setStatus(null);
    setAsking(false);
    setUploading(false);
    setUploadName(null);
  };

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF uploads are supported");
      return;
    }
    if (!activeChat) {
      setError("Create a chat first");
      return;
    }
    const chatId = activeChat.id;
    setError(null);
    setUploadName(file.name);
    setStatus(`Uploading ${file.name}…`);
    setUploading(true);
    try {
      const result = await ingestPdf(file);
      // Attach to this chat only — fresh turns; other chats keep their own history.
      // Reused store docs share doc_id but never share chat turns.
      const doc: DocSummary = {
        doc_id: result.doc_id,
        title: result.filename,
        source_name: result.filename,
        filename: result.filename,
      };
      const title = formatDocName(doc) || result.filename || "Document";

      askRequestId.current += 1;
      askScope.current = { chatId, docId: result.doc_id };

      setChats((prev) => {
        const next = prev.map((c) =>
          c.id === chatId
            ? {
                ...c,
                title,
                docId: result.doc_id,
                doc,
                turns: [],
              }
            : c,
        );
        saveChats(next, chatId);
        return next;
      });
      setActiveChatId(chatId);
      setStatus(`Ready · ${result.filename}`);
      // Refresh catalog in background (duplicate uploads already have the doc).
      void listDocuments().catch(() => undefined);
      return;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setStatus(null);
    } finally {
      setUploading(false);
      setUploadName(null);
    }
  };

  const handleAsk = async (question: string) => {
    if (!activeChat?.docId) {
      setError("Upload a PDF in this chat first");
      return;
    }
    if (asking) return;

    const requestId = ++askRequestId.current;
    const chatId = activeChat.id;
    const docId = activeChat.docId;
    askScope.current = { chatId, docId };

    setError(null);
    const history = activeChat.turns.map((turn) => ({
      role: turn.role,
      text: turn.text,
      quotes: turn.answer?.quotes,
      status: turn.answer?.status,
    }));

    const userTurn: ChatTurn = {
      id: nextTurnId("u"),
      role: "user",
      text: question,
    };
    patchActiveChat({ turns: [...activeChat.turns, userTurn] });
    setAsking(true);

    try {
      const answer = await askQuestion(docId, question, history);
      if (
        requestId !== askRequestId.current ||
        askScope.current?.chatId !== chatId ||
        askScope.current?.docId !== docId
      ) {
        return;
      }
      setChats((prev) => {
        const next = prev.map((c) => {
          if (c.id !== chatId) return c;
          return {
            ...c,
            turns: [
              ...c.turns,
              {
                id: answer.question_id || nextTurnId("a"),
                role: "assistant" as const,
                text: answer.text,
                answer,
              },
            ],
          };
        });
        saveChats(next, chatId);
        return next;
      });
    } catch (err) {
      if (requestId !== askRequestId.current) return;
      setError(err instanceof Error ? err.message : "Ask failed");
    } finally {
      if (requestId === askRequestId.current) {
        setAsking(false);
      }
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-canvas">
      <SidebarNav
        chats={chatItems}
        activeChatId={activeChatId}
        userEmail={userEmail}
        uploadDisabled={uploading}
        onNewChat={handleNewChat}
        onPickChat={handlePickChat}
        onDeleteChat={(id) => void handleDeleteChat(id)}
        onUploadClick={() => {
          if (!uploading) fileRef.current?.click();
        }}
        onLogout={() => void handleLogout()}
      />
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleUpload(file);
          event.target.value = "";
        }}
      />

      <main className="relative flex min-w-0 flex-1 flex-col">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 app-ambient"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-[420px] app-grid opacity-60"
        />

        <header className="relative z-20 flex shrink-0 flex-col border-b border-line/80 bg-canvas/85 backdrop-blur-md">
          <div className="flex h-14 items-center justify-between gap-4 px-5">
            <div className="min-w-0">
              {activeDoc ? (
                <button
                  type="button"
                  onClick={() => setPreviewOpen(true)}
                  className="group flex max-w-full items-center gap-2 rounded-[10px] text-left transition hover:bg-hover-2/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
                  title="Open document preview"
                >
                  <span className="hidden size-1.5 shrink-0 rounded-full bg-green sm:inline-block" />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate text-[13.5px] font-semibold tracking-[-0.015em] text-ink group-hover:text-accent-ink">
                        {formatDocName(activeDoc)}
                      </span>
                      <span className="hidden shrink-0 rounded-[6px] bg-accent-tint px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.04em] text-accent-ink sm:inline">
                        Preview
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-ink-3">
                      {status ??
                        `${activeDoc.page_count ?? "?"} pages · click to preview · this chat only`}
                    </span>
                  </span>
                </button>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className="hidden size-1.5 rounded-full bg-green sm:inline-block" />
                    <p className="truncate text-[13.5px] font-semibold tracking-[-0.015em] text-ink">
                      {activeChat?.title || "New chat"}
                    </p>
                  </div>
                  <p className="mt-0.5 truncate text-[11.5px] text-ink-3">
                    {status ??
                      (uploading
                        ? "Uploading…"
                        : "New chat · upload a PDF to begin")}
                  </p>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Link
                href="/docs"
                className="hidden rounded-[8px] px-2.5 py-1 text-[12px] font-medium text-ink-2 transition hover:bg-hover-2 hover:text-ink sm:inline"
              >
                Docs
              </Link>
              <BudgetMeter
                used={asking ? Math.min(6, lastCallsUsed || 1) : lastCallsUsed}
              />
            </div>
          </div>
          {activeDoc ? (
            <div className="flex items-center gap-2 border-t border-line/70 bg-accent-tint/40 px-5 py-2">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-[6px] bg-accent text-[9px] font-bold text-white">
                PDF
              </span>
              <button
                type="button"
                onClick={() => setPreviewOpen(true)}
                className="min-w-0 flex-1 truncate text-left text-[12.5px] font-medium text-ink transition hover:text-accent-ink"
              >
                {formatDocName(activeDoc)}
                <span className="text-ink-3">
                  {" "}
                  · {activeDoc.page_count ?? "?"} pages · open preview
                </span>
              </button>
            </div>
          ) : null}
        </header>

        <DocPreviewModal
          doc={activeDoc}
          open={previewOpen && Boolean(activeDoc)}
          onClose={() => setPreviewOpen(false)}
        />

        <div
          ref={scrollerRef}
          className="relative z-10 flex min-h-0 flex-1 flex-col overflow-y-auto px-5 py-6"
        >
          <div className="mx-auto flex w-full max-w-[42rem] flex-col gap-5">
            {uploading && uploadName ? (
              <UploadProgress filename={uploadName} />
            ) : null}

            {turns.length === 0 && !asking && !uploading && (
              <div className="flex flex-col gap-8 pt-2 sm:pt-6">
                <div className="turn-enter">
                  <p className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-ink-3">
                    {activeDoc ? "This chat" : "New chat"}
                  </p>
                  <h1 className="mt-2 text-[30px] font-semibold tracking-[-0.035em] text-ink sm:text-[36px]">
                    {activeDoc ? (
                      formatDocName(activeDoc)
                    ) : (
                      <>
                        Six<span className="text-accent">Call</span>
                      </>
                    )}
                  </h1>
                  <p className="mt-2.5 max-w-lg text-[14px] leading-relaxed text-ink-2">
                    {activeDoc
                      ? `Ask about ${formatDocName(activeDoc)}. Only this PDF is in scope for this chat.`
                      : "This chat is empty. Upload a PDF here — documents from other chats stay out of this thread."}
                  </p>
                </div>

                <ContextCards
                  docs={chatDocs}
                  activeDocId={activeDoc?.doc_id ?? null}
                  emptyHint="Click here to upload a PDF for this chat only."
                  onUpload={() => {
                    if (!uploading) fileRef.current?.click();
                  }}
                />

                {activeDoc ? (
                  <div
                    className="turn-enter"
                    style={{ animationDelay: "80ms" }}
                  >
                    <p className="mb-2 text-[12px] font-medium text-ink-3">
                      Try asking
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {SUGGESTIONS.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          disabled={asking || uploading}
                          onClick={() => void handleAsk(prompt)}
                          className="rounded-full border border-line bg-surface/90 px-3 py-1.5 text-[12.5px] text-ink-2 shadow-hairline transition hover:border-accent/40 hover:bg-accent-tint hover:text-accent-ink disabled:opacity-50"
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {turns.map((turn, turnIndex) => {
              if (turn.role === "user") {
                return (
                  <div
                    key={`${turn.id}-${turnIndex}`}
                    className="turn-enter flex justify-end pl-10 sm:pl-16"
                  >
                    <div className="max-w-[85%] rounded-[16px] rounded-br-[6px] bg-accent px-3.5 py-2 text-[13.5px] leading-[1.45] text-white shadow-btn">
                      {turn.text}
                    </div>
                  </div>
                );
              }

              const answer = turn.answer;
              const ok = answer?.status === "ok";
              const reason = (answer?.reason || "").trim();
              const body = (turn.text || "").trim();
              const reasonAlreadyInBody =
                !!reason &&
                body.toLowerCase().includes(reason.toLowerCase().slice(0, 40));
              const displayText =
                !ok && reason && !reasonAlreadyInBody
                  ? `${body}\n\n${reason}`
                  : body;
              return (
                <div
                  key={`${turn.id}-${turnIndex}`}
                  className="turn-enter flex flex-col gap-3"
                >
                  {" "}
                  <ThinkingState
                    rows={thinkingRows(answer)}
                    active="Working"
                    done={`Used ${answer?.calls_used ?? 0}/6 calls`}
                    working={false}
                  />
                  <div className="answer-panel rounded-[16px] px-4 py-3.5">
                    <div className="mb-2.5 flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          ok
                            ? "bg-green-tint text-green"
                            : "bg-orange/15 text-orange"
                        }`}
                      >
                        {ok ? "Verified" : "Insufficient"}
                      </span>
                      {answer?.strategy ? (
                        <span className="font-mono text-[11px] text-ink-3">
                          {answer.strategy}
                        </span>
                      ) : null}
                      {answer?.pages_used?.length ? (
                        <span className="font-mono text-[11px] text-ink-3">
                          p.{answer.pages_used.join(", ")}
                        </span>
                      ) : null}
                    </div>
                    <StreamingText
                      content={tokensFromText(displayText)}
                      sources={answer ? sourcesFromAnswer(answer) : []}
                      instant
                    />
                  </div>
                </div>
              );
            })}

            {asking && (
              <div className="turn-enter flex flex-col gap-3">
                <div className="answer-panel rounded-[16px] px-4 py-3.5">
                  <LoadingState label="Running agent" variant="Drive" />
                  <div className="mt-3">
                    <ThinkingState
                      rows={thinkingRows(undefined, true)}
                      working
                      active="Thinking"
                    />
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="turn-enter rounded-card bg-red-tint px-3.5 py-2.5 text-[12.5px] text-red">
                {error}
              </div>
            )}
          </div>
        </div>

        <div className="relative z-10 shrink-0 border-t border-line/80 bg-canvas/80 px-5 py-3.5 backdrop-blur-md">
          <div className="mx-auto w-full max-w-[42rem]">
            <PromptBar
              disabled={asking || uploading}
              placeholder={
                activeDoc
                  ? "Ask a question or follow up on the last answer…"
                  : "Upload a PDF into this chat, then ask…"
              }
              onSend={(text) => void handleAsk(text)}
              onAttach={(file) => void handleUpload(file)}
            />
            <p className="mt-2 text-center text-[11px] text-ink-3">
              Each chat has its own PDF · New chat stays empty until you upload
              · Enter to send
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
