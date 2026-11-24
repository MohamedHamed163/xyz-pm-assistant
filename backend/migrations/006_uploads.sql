-- Upload feature: PDF/DOCX → parsing → draft (review) → publish → processing (embedding) → ready.
-- Drafts live in document_versions + document_sections. They are never searchable: no chunks exist
-- until publish, and section RLS only exposes a document's CURRENT version.

ALTER TABLE document_versions DROP CONSTRAINT document_versions_status_check;
ALTER TABLE document_versions ADD CONSTRAINT document_versions_status_check CHECK (status IN (
  'parsing',     -- uploaded file waiting for / in the parser
  'draft',       -- parsed; uploader is reviewing sections and visibility
  'processing',  -- published (or markdown seed); waiting for / in embedding
  'ready', 'failed', 'superseded',
  'discarded'    -- draft thrown away by the uploader or expired
));

ALTER TABLE document_versions ALTER COLUMN source_text DROP NOT NULL;
ALTER TABLE document_versions
  ADD COLUMN source_kind text NOT NULL DEFAULT 'markdown' CHECK (source_kind IN ('markdown', 'pdf', 'docx')),
  ADD COLUMN file_key text,                                  -- storage key (sha256) of the original file
  ADD COLUMN file_name text,
  ADD COLUMN file_size bigint,
  ADD COLUMN page_count int,
  ADD COLUMN base_version_id bigint REFERENCES document_versions(id),  -- live version when the draft began
  ADD COLUMN drafted_by text REFERENCES users(id),
  ADD COLUMN published_by text REFERENCES users(id),
  ADD COLUMN published_at timestamptz,
  ADD COLUMN draft_expires_at timestamptz;

-- Nightly cleanup reads only drafts; "My uploads" reads only the uploader's open drafts.
CREATE INDEX document_versions_draft_expiry_idx ON document_versions (draft_expires_at) WHERE status = 'draft';
CREATE INDEX document_versions_my_uploads_idx ON document_versions (drafted_by, created_at DESC)
  WHERE status IN ('parsing', 'draft');
CREATE INDEX document_versions_parse_queue_idx ON document_versions (next_attempt_at) WHERE status = 'parsing';

-- Who set which section to which level, and when (publish and later live edits).
CREATE TABLE visibility_changes (
  id             bigserial PRIMARY KEY,
  document_id    text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_id     bigint NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  ordinal        int NOT NULL,
  heading        text NOT NULL,
  old_visibility text,
  new_visibility text NOT NULL,
  context        text NOT NULL CHECK (context IN ('publish', 'live_edit', 'restore')),
  changed_by     text NOT NULL REFERENCES users(id),
  changed_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX visibility_changes_document_idx ON visibility_changes (document_id, changed_at DESC);
