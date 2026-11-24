import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  type Draft,
  type Level,
  type ManagedDocument,
  type Me,
  type UploadItem,
  type UploadOptions,
} from "./api";
import { LEVEL_META, LevelPicker } from "./levels";
import Review from "./Review";

type Tab = "upload" | "uploads" | "live";

const STATUS_LABEL: Record<UploadItem["status"], string> = {
  parsing: "Parsing…",
  draft: "Draft — needs review",
  processing: "Publishing…",
  ready: "Live",
  failed: "Failed",
  superseded: "Replaced",
};

export default function Documents({ me, onBack }: { me: Me; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("upload");
  const [reviewing, setReviewing] = useState<Draft | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  async function openReview(id: number) {
    setReviewing(await api.upload(id));
  }

  function doneReviewing(message: string) {
    setReviewing(null);
    setFlash(message);
    setTab("uploads");
  }

  return (
    <div className="docs-page">
      <header className="topbar">
        <button className="link-btn" onClick={reviewing ? () => setReviewing(null) : onBack}>
          ← {reviewing ? "Back to documents" : "Back to chat"}
        </button>
        <span className="topbar-title">{reviewing ? "Review sections" : "Documents"}</span>
        <span className={`role-badge role-${me.role}`}>{me.name}</span>
      </header>

      <main className="docs-main">
        {reviewing ? (
          <Review draft={reviewing} onDone={doneReviewing} />
        ) : (
          <>
            <nav className="tabs" role="tablist">
              {(
                [
                  ["upload", "Upload"],
                  ["uploads", "My uploads"],
                  ["live", "Live documents"],
                ] as [Tab, string][]
              ).map(([t, label]) => (
                <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
                  {label}
                </button>
              ))}
            </nav>
            {flash && (
              <p className="notice-bar" role="status">
                {flash}
                <button className="icon-btn" aria-label="Dismiss" onClick={() => setFlash(null)}>
                  ×
                </button>
              </p>
            )}
            {tab === "upload" && (
              <UploadForm
                onUploaded={(id) => {
                  setFlash("Uploaded — parsing the file…");
                  setTab("uploads");
                  pollUntilParsed(id, openReview, setFlash);
                }}
              />
            )}
            {tab === "uploads" && <MyUploads onOpen={openReview} />}
            {tab === "live" && <LiveDocuments />}
          </>
        )}
      </main>
    </div>
  );
}

async function pollUntilParsed(id: number, open: (id: number) => void, flash: (m: string) => void) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const d = await api.upload(id).catch(() => null);
    if (d?.status === "draft") return open(id);
    if (d?.status === "failed") return flash(`Couldn't read “${d.file_name}”: ${d.error}`);
  }
}

// ---------------------------------------------------------------------------------------------

function UploadForm({ onUploaded }: { onUploaded: (versionId: number) => void }) {
  const [options, setOptions] = useState<UploadOptions | null>(null);
  const [docs, setDocs] = useState<ManagedDocument[]>([]);
  const [mode, setMode] = useState<"new" | "version">("new");
  const [file, setFile] = useState<File | null>(null);
  const [project, setProject] = useState("");
  const [docType, setDocType] = useState("");
  const [title, setTitle] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.uploadOptions().then((o) => {
      setOptions(o);
      setProject(o.projects[0]?.id ?? "");
      setDocType(o.doc_types[0]?.name ?? "");
    });
    api.managedDocuments().then((r) => setDocs(r.items));
  }, []);

  function pick(f: File | null) {
    setError(null);
    if (!f) return setFile(null);
    if (!/\.(pdf|docx)$/i.test(f.name)) return setError("Choose a PDF or Word (.docx) file.");
    if (f.size > 20 * 1024 * 1024) return setError("Files can be at most 20 MB.");
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.(pdf|docx)$/i, ""));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.createUpload(
        file,
        mode === "version" ? { document_id: documentId } : { doc_type: docType, project_id: project, title },
      );
      onUploaded(r.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  if (!options) return <p className="muted pad">Loading…</p>;

  return (
    <form className="upload-form" onSubmit={submit}>
      <div
        className={`dropzone ${file ? "has-file" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pick(e.dataTransfer.files[0] ?? null);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      >
        <input ref={input} type="file" accept=".pdf,.docx" hidden onChange={(e) => pick(e.target.files?.[0] ?? null)} />
        {file ? (
          <>
            <strong>{file.name}</strong>
            <span className="muted small">{(file.size / 1024).toFixed(0)} KB · click to change</span>
          </>
        ) : (
          <>
            <strong>Drop a PDF or Word file here</strong>
            <span className="muted small">or click to choose · max 20 MB, 300 pages</span>
          </>
        )}
      </div>

      <fieldset className="mode">
        <label className="check">
          <input type="radio" checked={mode === "new"} onChange={() => setMode("new")} /> New document
        </label>
        <label className="check">
          <input type="radio" checked={mode === "version"} onChange={() => setMode("version")} disabled={!docs.length} /> New
          version of an existing document
        </label>
      </fieldset>

      {mode === "new" ? (
        <div className="form-grid">
          <label>
            Project
            <select value={project} onChange={(e) => setProject(e.target.value)}>
              {options.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id} · {p.name}
                </option>
              ))}
              {options.company_wide && <option value="">Company-wide (no project)</option>}
            </select>
          </label>
          <label>
            Document type
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              {options.doc_types.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
          </label>
        </div>
      ) : (
        <label className="wide">
          Document
          <select value={documentId} onChange={(e) => setDocumentId(e.target.value)} required>
            <option value="">Choose…</option>
            {docs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.project_id ?? "Company"} · {d.title}
              </option>
            ))}
          </select>
          <span className="muted small">Project and type stay the same. Section levels you chose before are reused.</span>
        </label>
      )}

      <p className="muted small">
        Every section starts as <strong>{LEVEL_META.team.label}</strong> ({LEVEL_META.team.who}). You choose what to share
        with the client before anything is published.
      </p>
      {error && <p className="error-text">{error}</p>}
      <button className="btn-primary" type="submit" disabled={!file || busy || (mode === "version" && !documentId)}>
        {busy ? "Uploading…" : "Upload and review"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------------------------

function MyUploads({ onOpen }: { onOpen: (id: number) => void }) {
  const [items, setItems] = useState<UploadItem[] | null>(null);

  const load = useCallback(() => api.uploads().then((r) => setItems(r.items)), []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while something is still being parsed or published.
  useEffect(() => {
    if (!items?.some((u) => u.status === "parsing" || u.status === "processing")) return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [items, load]);

  if (!items) return <p className="muted pad">Loading…</p>;
  if (!items.length) return <p className="muted pad">No uploads yet.</p>;

  return (
    <ul className="upload-list">
      {items.map((u) => (
        <li key={u.id} className="upload-item">
          <div className="upload-main">
            <strong>{u.title}</strong>
            <span className="muted small">
              {u.project_id ?? "Company-wide"} · {u.doc_type.toUpperCase()} · {u.file_name}
              {u.is_new_version ? " · new version" : ""} · {new Date(u.created_at).toLocaleString()}
            </span>
            {u.error && <span className="error-text small">{u.error}</span>}
          </div>
          <span className={`status status-${u.status}`}>{STATUS_LABEL[u.status]}</span>
          {(u.status === "draft" || u.status === "failed") && (
            <button className="btn-secondary" onClick={() => onOpen(u.id)}>
              {u.status === "draft" ? "Review" : "Open"}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------------------------

function LiveDocuments() {
  const [docs, setDocs] = useState<ManagedDocument[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => api.managedDocuments().then((r) => setDocs(r.items)), []);
  useEffect(() => {
    load();
  }, [load]);

  async function change(doc: ManagedDocument, ordinal: number, heading: string, level: Level) {
    if (level === "client_shared" && !confirm(`Share “${heading}” with the client${doc.client_name ? ` (${doc.client_name})` : ""}? It becomes visible immediately.`))
      return;
    try {
      await api.setVisibility(doc.id, ordinal, level);
      setMessage(`“${heading}” is now ${LEVEL_META[level].label.toLowerCase()} — effective immediately.`);
      load();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Change failed");
    }
  }

  async function restore(doc: ManagedDocument) {
    if (!confirm(`Restore the previous version of “${doc.title}”? The current version stops being searchable.`)) return;
    try {
      await api.restorePrevious(doc.id);
      setMessage(`Restored the previous version of “${doc.title}”.`);
      load();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Restore failed");
    }
  }

  if (!docs) return <p className="muted pad">Loading…</p>;
  return (
    <div className="live-docs">
      {message && <p className="notice-bar" role="status">{message}</p>}
      {docs.map((d) => (
        <section key={d.id} className="live-doc">
          <button className="live-doc-head" onClick={() => setOpen(open === d.id ? null : d.id)} aria-expanded={open === d.id}>
            <span>
              <strong>{d.title}</strong>
              <span className="muted small">
                {" "}
                · {d.project_id ?? "Company-wide"} · {d.doc_type.toUpperCase()} · {d.sections.length} sections
              </span>
            </span>
            <span className="level-dots" aria-hidden>
              {d.sections.map((s) => (
                <i key={s.ordinal} className={`dot level-${s.visibility}`} />
              ))}
            </span>
          </button>
          {open === d.id && (
            <div className="live-doc-body">
              {d.sections.map((s) => (
                <div key={s.ordinal} className="live-section">
                  <span>{s.heading}</span>
                  <LevelPicker value={s.visibility} name={s.heading} onChange={(l) => l !== s.visibility && change(d, s.ordinal, s.heading, l)} />
                </div>
              ))}
              {d.can_restore && (
                <button className="link-btn danger" onClick={() => restore(d)}>
                  Restore previous version
                </button>
              )}
            </div>
          )}
        </section>
      ))}
      {docs.length === 0 && <p className="muted pad">No documents you can manage yet.</p>}
    </div>
  );
}
