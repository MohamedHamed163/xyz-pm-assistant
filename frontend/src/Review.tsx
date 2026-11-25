import { useMemo, useState } from "react";
import { api, ApiError, type Draft, type DraftSection, type TopicInfo } from "./api";
import { DOC_TYPE_LABEL, TopicSelect, whoCanRead } from "./topics";

// Review a parsed upload: check the automatic topic of each section, rename, merge or split, then
// publish. Who can read each topic is fixed by the rules — the reviewer only checks the tags.
// The text itself can't be edited; the backend rejects any change to it.

export default function Review({
  draft: initial,
  topics,
  onDone,
}: {
  draft: Draft;
  topics: TopicInfo[];
  onDone: (message: string) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [sections, setSections] = useState<DraftSection[]>(initial.sections);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<string>(initial.unclassified ? "unclassified" : "all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [splitting, setSplitting] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const editable = draft.status === "draft";
  const canPublish = editable || (draft.status === "failed" && draft.published);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    sections.forEach((s) => (c[s.topic] = (c[s.topic] ?? 0) + 1));
    return c;
  }, [sections]);
  const unclassified = counts.unclassified ?? 0;

  const shown = sections
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => (filter === "all" ? true : filter === "changed" ? s.changed : s.topic === filter))
    .filter(({ s }) => !query || `${s.heading} ${s.content}`.toLowerCase().includes(query.toLowerCase()));

  const update = (i: number, patch: Partial<DraftSection>) =>
    setSections((all) => all.map((s, j) => (j === i ? { ...s, ...patch } : s)));

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
      // Different topics can't be merged blindly: the merged section stays unclassified until chosen.
      const topic = a.topic === b.topic ? a.topic : "unclassified";
      return [...all.slice(0, i), { ...a, content: `${a.content}\n\n${b.content}`, topic, changed: true }, ...all.slice(i + 2)];
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
  }

  async function save(): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveSections(draft.id, sections, draft.lock_version);
      setDraft(saved);
      setSections(saved.sections);
      return true;
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Couldn't save";
      setError(message);
      if (e instanceof ApiError && e.status === 409) setStale(true);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function reload() {
    const fresh = await api.upload(draft.id);
    setDraft(fresh);
    setSections(fresh.sections);
    setStale(false);
    setError(null);
  }

  async function publish() {
    if (editable && !(await save())) return setConfirming(false);
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
            {draft.project_id} · {draft.project_name} · {DOC_TYPE_LABEL[draft.doc_type] ?? draft.doc_type} · {draft.file_name}
            {draft.page_count ? ` · ${draft.page_count} pages` : ""} · {sections.length} sections
            {draft.is_new_version ? " · new version" : ""}
          </p>
        </div>
        {draft.can_download && (
          <button className="link-btn" onClick={() => api.downloadOriginal(draft.id, draft.file_name)}>
            Download original
          </button>
        )}
      </header>

      {unclassified > 0 && (
        <p className="notice-bar warn">
          <span>
            <strong>{unclassified} section{unclassified > 1 ? "s need" : " needs"} a topic.</strong> Unclassified
            sections are readable by CEO and PM only, and the document can't be published until every section has a topic.
          </span>
        </p>
      )}
      {draft.status === "failed" && draft.published && (
        <p className="notice-bar error">Publishing failed: {draft.error}. You can try again.</p>
      )}
      {stale && (
        <p className="notice-bar error">
          {error}
          <button className="btn-secondary" onClick={reload}>
            Reload
          </button>
        </p>
      )}

      <div className="review-tools">
        <label className="check">
          <input
            type="checkbox"
            checked={allShownSelected}
            onChange={() => setSelected(allShownSelected ? new Set() : new Set([...selected, ...shown.map(({ i }) => i)]))}
          />
          {selected.size ? `${selected.size} selected` : "Select all"}
        </label>
        {selected.size > 0 && editable && (
          <div className="bulk">
            Set to
            <TopicSelect
              topics={topics}
              value={null}
              label="Topic for selected sections"
              placeholder="Choose topic…"
              onChange={(t) => setSections((all) => all.map((s, i) => (selected.has(i) ? { ...s, topic: t } : s)))}
            />
          </div>
        )}
        <div className="spacer" />
        <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter sections">
          <option value="all">All sections</option>
          <option value="unclassified">⚠ Needs a topic ({unclassified})</option>
          <option value="changed">New / changed</option>
          {topics
            .filter((t) => t.key !== "unclassified")
            .map((t) => (
              <option key={t.key} value={t.key}>
                {t.label} ({counts[t.key] ?? 0})
              </option>
            ))}
        </select>
        <input className="search" placeholder="Search sections" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <ol className="section-list">
        {shown.map(({ s, i }) => {
          const paragraphs = s.content.split(/\n\s*\n/);
          return (
            <li key={i} className={`section-card ${s.topic === "unclassified" ? "needs-topic" : ""} ${selected.has(i) ? "selected" : ""}`}>
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
                <TopicSelect topics={topics} value={s.topic} label={`Topic of ${s.heading}`} disabled={!editable}
                  onChange={(t) => update(i, { topic: t })} />
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
                <span className="muted small">Readable by: {whoCanRead(topics, s.topic)}</span>
              </div>
            </li>
          );
        })}
        {shown.length === 0 && <p className="muted pad">No sections match.</p>}
      </ol>

      <footer className="review-foot">
        <div className="summary">
          {unclassified ? `${unclassified} still ${unclassified > 1 ? "need" : "needs"} a topic` : "Every section has a topic"}
          {draft.last_edited_by ? <span className="muted small"> · last saved by {draft.last_edited_by}</span> : null}
        </div>
        {error && !stale && <p className="error-text">{error}</p>}
        <div className="foot-actions">
          {editable && (
            <>
              <button className="link-btn danger" onClick={discard} disabled={busy}>
                Discard
              </button>
              <button className="btn-secondary" onClick={() => save().then((ok) => ok && onDone("Draft saved."))} disabled={busy || stale}>
                Save draft
              </button>
            </>
          )}
          {canPublish && (
            <button
              className="btn-primary"
              onClick={() => setConfirming(true)}
              disabled={busy || stale || unclassified > 0}
              title={unclassified ? "Give every section a topic first" : undefined}
            >
              Publish…
            </button>
          )}
        </div>
      </footer>

      {confirming && (
        <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="modal">
            <h3 id="confirm-title">Publish “{draft.title}”?</h3>
            <p className="muted small">Each topic is readable by these roles in {draft.project_name}:</p>
            <ul className="confirm-list">
              {topics
                .filter((t) => counts[t.key])
                .map((t) => (
                  <li key={t.key} className={t.key === "commercial" ? "topic-commercial" : ""}>
                    <strong>{t.label}</strong> ({counts[t.key]}) — {t.roles.join(", ")}
                  </li>
                ))}
            </ul>
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
