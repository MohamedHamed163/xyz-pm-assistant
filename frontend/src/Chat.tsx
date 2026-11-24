import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, ApiError, type Citation, type Conversation, type Me, type Message, type Source } from "./api";
import { MessageBody } from "./MessageBody";
import { ROLE_LABEL, SUGGESTIONS } from "./roles";

const MAX_QUESTION = 2000;

type SourceState =
  | { status: "loading"; citation: Citation }
  | { status: "ok"; citation: Citation; source: Source }
  | { status: "gone"; citation: Citation };

export default function Chat({
  me,
  onLogout,
  onOpenDocuments,
}: {
  me: Me;
  onLogout: () => void;
  onOpenDocuments: () => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convCursor, setConvCursor] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadingThread, setLoadingThread] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ question: string; error: string } | null>(null);
  const [draft, setDraft] = useState("");
  const [source, setSource] = useState<SourceState | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const threadEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.conversations().then((r) => {
      setConversations(r.items);
      setConvCursor(r.next_cursor);
    });
  }, []);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  const openConversation = useCallback(async (id: number) => {
    setActiveId(id);
    setSidebarOpen(false);
    setFailed(null);
    setSource(null);
    setLoadingThread(true);
    try {
      const r = await api.messages(id);
      setMessages(r.items);
      setOlderCursor(r.next_before);
    } finally {
      setLoadingThread(false);
    }
  }, []);

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setOlderCursor(null);
    setFailed(null);
    setSource(null);
    setSidebarOpen(false);
    input.current?.focus();
  }

  async function loadOlder() {
    if (!activeId || !olderCursor) return;
    const r = await api.messages(activeId, olderCursor);
    setMessages((m) => [...r.items, ...m]);
    setOlderCursor(r.next_before);
  }

  async function loadMoreConversations() {
    if (!convCursor) return;
    const r = await api.conversations(convCursor);
    setConversations((c) => [...c, ...r.items]);
    setConvCursor(r.next_cursor);
  }

  async function deleteConversation(id: number) {
    await api.deleteConversation(id);
    setConversations((c) => c.filter((x) => x.id !== id));
    if (id === activeId) newChat();
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || pending) return;
    setDraft("");
    setFailed(null);
    setPending(question);
    try {
      let id = activeId;
      if (id === null) {
        const conv = await api.createConversation();
        id = conv.id;
        setActiveId(id);
        setConversations((c) => [conv, ...c]);
      }
      const r = await api.ask(id, question);
      setMessages((m) => [...m, r.user_message, r.assistant_message]);
      setConversations((cs) => {
        const current = cs.find((c) => c.id === id);
        const updated = { ...(current as Conversation), title: r.conversation_title, updated_at: r.assistant_message.created_at };
        return [updated, ...cs.filter((c) => c.id !== id)];
      });
    } catch (e) {
      setFailed({ question, error: e instanceof ApiError ? e.message : "Something went wrong" });
    } finally {
      setPending(null);
      input.current?.focus();
    }
  }

  async function openSource(citation: Citation) {
    setSource({ status: "loading", citation });
    try {
      const s = await api.source(citation.chunk_id);
      setSource({ status: "ok", citation, source: s });
    } catch {
      setSource({ status: "gone", citation });
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(draft);
    }
  }

  const scope = me.company_wide
    ? "All projects"
    : me.projects.length
      ? me.projects.map((p) => `${p.id} · ${p.name}`).join(", ")
      : "No projects assigned";

  return (
    <div className={`app ${source ? "with-source" : ""}`}>
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`} aria-label="Conversations">
        <div className="sidebar-head">
          <div className="brand small">
            <span className="brand-mark" aria-hidden>
              XYZ
            </span>
            <span>PM Assistant</span>
          </div>
          <button className="btn-primary block" onClick={newChat}>
            + New chat
          </button>
          {me.can_upload && (
            <button className="btn-secondary block" onClick={onOpenDocuments}>
              Documents
            </button>
          )}
        </div>

        <nav className="conv-list">
          {conversations.length === 0 && <p className="muted small pad">No conversations yet.</p>}
          {conversations.map((c) => (
            <div key={c.id} className={`conv-item ${c.id === activeId ? "active" : ""}`}>
              <button className="conv-title" onClick={() => openConversation(c.id)} title={c.title}>
                {c.title}
              </button>
              <button className="icon-btn" aria-label={`Delete “${c.title}”`} onClick={() => deleteConversation(c.id)}>
                ×
              </button>
            </div>
          ))}
          {convCursor && (
            <button className="link-btn" onClick={loadMoreConversations}>
              Load more
            </button>
          )}
        </nav>

        <div className="me-card">
          <span className={`avatar role-${me.role}`} aria-hidden>
            {me.name[0]}
          </span>
          <div className="me-body">
            <div className="me-name">{me.name}</div>
            <span className={`role-badge role-${me.role}`}>{ROLE_LABEL[me.role] ?? me.role}</span>
            <div className="me-scope">{scope}</div>
            {me.client_view && <div className="me-scope">Client view: shared sections only</div>}
          </div>
          <button className="link-btn" onClick={onLogout}>
            Switch user
          </button>
        </div>
      </aside>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu" aria-label="Open conversations" onClick={() => setSidebarOpen(true)}>
            ☰
          </button>
          <span className="topbar-title">
            {activeId ? conversations.find((c) => c.id === activeId)?.title : "New chat"}
          </span>
          <span className={`role-badge role-${me.role}`}>{me.name}</span>
        </header>

        <div className="thread" aria-live="polite">
          {olderCursor && (
            <button className="link-btn center" onClick={loadOlder}>
              Load earlier messages
            </button>
          )}
          {loadingThread && <p className="muted center">Loading…</p>}

          {!loadingThread && messages.length === 0 && !pending && (
            <div className="empty">
              <h2>Hi {me.name}, what do you need to know?</h2>
              <p className="muted">Chat freely. Facts about your projects come only from documents you're allowed to read, with sources.</p>
              <div className="suggestions">
                {(SUGGESTIONS[me.role] ?? []).map((s) => (
                  <button key={s} className="suggestion" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <MessageBody key={m.id} message={m} onOpenSource={openSource} />
          ))}

          {pending && (
            <>
              <div className="msg user">
                <div className="bubble">{pending}</div>
              </div>
              <div className="msg assistant">
                <div className="bubble typing" aria-label="Assistant is answering">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </>
          )}

          {failed && (
            <div className="msg assistant">
              <div className="bubble notice error" role="alert">
                <strong>Couldn't send.</strong> {failed.error}
                <button className="link-btn" onClick={() => send(failed.question)}>
                  Retry
                </button>
              </div>
            </div>
          )}
          <div ref={threadEnd} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <textarea
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, MAX_QUESTION))}
            onKeyDown={onKeyDown}
            placeholder="Message the assistant — ask about your projects, or just chat…"
            rows={1}
            aria-label="Your question"
            disabled={pending !== null}
          />
          <button className="btn-primary" type="submit" disabled={!draft.trim() || pending !== null}>
            Ask
          </button>
          {draft.length > MAX_QUESTION * 0.9 && (
            <span className="counter">
              {draft.length}/{MAX_QUESTION}
            </span>
          )}
        </form>
      </main>

      {source && (
        <aside className="source-panel" aria-label="Source">
          <div className="source-head">
            <span className="source-num">[{source.citation.number}]</span>
            <div>
              <div className="source-title">{source.citation.document_title}</div>
              <div className="muted small">{source.citation.heading}</div>
            </div>
            <button className="icon-btn" aria-label="Close source" onClick={() => setSource(null)}>
              ×
            </button>
          </div>
          {source.status === "loading" && <p className="muted pad">Checking access…</p>}
          {source.status === "gone" && (
            <p className="notice pad">This source is no longer available to you.</p>
          )}
          {source.status === "ok" && (
            <div className="source-body">
              <MessageBody
                message={{ ...emptyAssistant, content: source.source.content }}
                onOpenSource={() => {}}
                bare
              />
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

const emptyAssistant: Message = {
  id: -1,
  role: "assistant",
  content: "",
  outcome: "answered",
  citations: [],
  created_at: "",
};
