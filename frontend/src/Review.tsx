import { useMemo, useState } from "react";
import { api, ApiError, type Draft, type DraftSection, type Level } from "./api";
import { LEVEL_META, LEVELS, LevelPicker, summaryText } from "./levels";

// Review a parsed upload: rename, merge, split, choose who sees each section, then publish.
// The text itself can't be edited — the backend rejects any change to it.

export default function Review({ draft, onDone }: { draft: Draft; onDone: (message: string) => void }) {
  const [sections, setSections] = useState<DraftSection[]>(draft.sections);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<Level | "all" | "changed">("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [splitting, setSplitting] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editable = draft.status === "draft" || (draft.status === "failed" && draft.published);

  const summary = useMemo(() => {
    const s: Record<Level, number> = { client_shared: 0, team: 0, management: 0 };
    sections.forEach((x) => s[x.visibility]++);
    return s;
  }, [sections]);

  const shown = sections
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => (filter === "all" ? true : filter === "changed" ? s.changed : s.visibility === filter))
    .filter(({ s }) => !query || `${s.heading} ${s.content}`.toLowerCase().includes(query.toLowerCase()));

  const update = (i: number, patch: Partial<DraftSection>) =>
    setSections((all) => all.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  function setLevelForSelected(level: Level) {
    setSections((all) => all.map((s, i) => (selected.has(i) ? { ...s, visibility: level } : s)));
  }

  function toggle(i: number) {
    setSelected((sel) => {
      const next = new Set(sel);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  function mergeWithNext(i: number) {
    setSections((all) => {
      const a = all[i], b = all[i + 1];
      // Merged text keeps the more restrictive level, so merging never widens access.
      const level = LEVELS.indexOf(a.visibility) >= LEVELS.indexOf(b.visibility) ? a.visibility : b.visibility;
      const merged = { ...a, content: `${a.content}\n\n${b.content}`, visibility: level, changed: true };
      return [...all.slice(0, i), merged, ...all.slice(i + 2)];
    });
    setSelected(new Set());
  }

  function splitAt(i: number, paragraph: number) {
    setSections((all) => {
      const parts = all[i].content.split(/\n\s*\n/);
      const first = { ...all[i], content: parts.slice(0, paragraph).join("\n\n"), changed: true };
      const second = { ...all[i], heading: `${all[i].heading} (part 2)`, content: parts.slice(paragraph).join("\n\n"), changed: true };
      return [...all.slice(0, i), first, second, ...all.slice(i + 1)];
    });
    setSplitting(null);
    setSelected(new Set());
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.saveSections(draft.id, sections);
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (draft.status === "draft" && !(await save())) return;
    setBusy(true);
    try {
      await api.publish(draft.id);
      onDone(`Publishing “${draft.title}” — it will be searchable in a moment.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't publish");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!confirm("Discard this upload? This can't be undone.")) return;
    await api.discard(draft.id);
    onDone(`Discarded “${draft.title}”.`);
  }

  const allShownSelected = shown.length > 0 && shown.every(({ i }) => selected.has(i));

  return (
    <div className="review">
      <header className="review-head">
        <div>
          <h2>{draft.title}</h2>
          <p className="muted small">
            {draft.project_id ?? "Company-wide"} · {draft.doc_type.toUpperCase()} · {draft.file_name}
            {draft.page_count ? ` · ${draft.page_count} pages` : ""} · {sections.length} sections
            {draft.is_new_version ? " · new version" : ""}
          </p>
        </div>
        <button className="link-btn" onClick={() => api.downloadOriginal(draft.id, draft.file_name)}>
          Download original
        </button>
      </header>

      {draft.status === "failed" && draft.published && (
        <p className="notice-bar error">Publishing failed: {draft.error}. You can try publishing again.</p>
      )}

      <div className="review-tools">
        <label className="check">
          <input
            type="checkbox"
            checked={allShownSelected}
            onChange={() =>
              setSelected(allShownSelected ? new Set() : new Set([...selected, ...shown.map(({ i }) => i)]))
            }
          />
          {selected.size ? `${selected.size} selected` : "Select all"}
        </label>
        {selected.size > 0 && (
          <div className="bulk">
            Set to
            <LevelPicker value={null} name="selected sections" onChange={setLevelForSelected} disabled={!editable} />
          </div>
        )}
        <div className="spacer" />
        <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} aria-label="Filter sections">
          <option value="all">All sections</option>
          <option value="changed">New / changed</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {LEVEL_META[l].label}
            </option>
          ))}
        </select>
        <input className="search" placeholder="Search sections" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <ol className="section-list">
        {shown.map(({ s, i }) => {
          const paragraphs = s.content.split(/\n\s*\n/);
          return (
            <li key={i} className={`section-card level-edge-${s.visibility} ${selected.has(i) ? "selected" : ""}`}>
              <div className="section-row">
                <input type="checkbox" checked={selected.has(i)} onChange={() => toggle(i)} aria-label={`Select ${s.heading}`} />
                <input
                  className="heading-input"
                  value={s.heading}
                  disabled={!editable}
                  maxLength={200}
                  onChange={(e) => update(i, { heading: e.target.value })}
                  aria-label="Section heading"
                />
                {s.changed && draft.is_new_version && <span className="badge">New / changed</span>}
                <LevelPicker value={s.visibility} name={s.heading} disabled={!editable} onChange={(v) => update(i, { visibility: v })} />
              </div>

              <div className={`section-preview ${expanded === i ? "open" : ""}`}>
                {splitting === i
                  ? paragraphs.map((p, n) => (
                      <div key={n}>
                        {n > 0 && (
                          <button className="split-here" onClick={() => splitAt(i, n)}>
                            ✂ Split here
                          </button>
                        )}
                        <p>{p}</p>
                      </div>
                    ))
                  : expanded === i
                    ? paragraphs.map((p, n) => <p key={n}>{p}</p>)
                    : <p>{s.content.slice(0, 220)}{s.content.length > 220 ? "…" : ""}</p>}
              </div>

              <div className="section-actions">
                <button className="link-btn" onClick={() => setExpanded(expanded === i ? null : i)}>
                  {expanded === i ? "Collapse" : "Show all"}
                </button>
                {editable && i < sections.length - 1 && !query && filter === "all" && (
                  <button className="link-btn" onClick={() => mergeWithNext(i)}>
                    Merge with next
                  </button>
                )}
                {editable && paragraphs.length > 1 && (
                  <button className="link-btn" onClick={() => setSplitting(splitting === i ? null : i)}>
                    {splitting === i ? "Cancel split" : "Split"}
                  </button>
                )}
                <span className="muted small">{LEVEL_META[s.visibility].who}</span>
              </div>
            </li>
          );
        })}
        {shown.length === 0 && <p className="muted pad">No sections match.</p>}
      </ol>

      <footer className="review-foot">
        <div className="summary">{summaryText(summary, draft.client_name)}</div>
        {error && <p className="error-text">{error}</p>}
        {editable && (
          <div className="foot-actions">
            {draft.status === "draft" && (
              <>
                <button className="link-btn danger" onClick={discard} disabled={busy}>
                  Discard
                </button>
                <button className="btn-secondary" onClick={() => save().then((ok) => ok && onDone("Draft saved."))} disabled={busy}>
                  Save draft
                </button>
              </>
            )}
            <button className="btn-primary" onClick={() => setConfirming(true)} disabled={busy}>
              Publish…
            </button>
          </div>
        )}
      </footer>

      {confirming && (
        <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="modal">
            <h3 id="confirm-title">Publish “{draft.title}”?</h3>
            <ul className="confirm-list">
              {summary.client_shared > 0 && (
                <li className="level-text-client_shared">
                  <strong>{summary.client_shared}</strong> section{summary.client_shared > 1 ? "s" : ""} will be visible to
                  the client{draft.client_name ? ` (${draft.client_name})` : ""}:
                  <span className="muted small">
                    {" "}
                    {sections.filter((s) => s.visibility === "client_shared").map((s) => s.heading).join(", ")}
                  </span>
                </li>
              )}
              <li>
                <strong>{summary.team}</strong> team (PM, developers, QA, CEO)
              </li>
              <li className="level-text-management">
                <strong>{summary.management}</strong> management only (PM and CEO)
              </li>
            </ul>
            <p className="muted small">You can change levels later from Live documents.</p>
            <div className="foot-actions">
              <button className="btn-secondary" onClick={() => setConfirming(false)} disabled={busy}>
                Back to review
              </button>
              <button className="btn-primary" onClick={publish} disabled={busy}>
                {busy ? "Publishing…" : "Confirm and publish"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
