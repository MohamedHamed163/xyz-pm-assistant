-- XYZ PM Assistant — initial schema.
-- See docs/design-decisions.md §5. Two database roles:
--   * the owner (migrations, seeding, ingestion worker) — bypasses RLS as table owner
--   * xyz_app (the question-answering path) — RLS is enforced on every content table

CREATE EXTENSION IF NOT EXISTS vector;

DO $$ BEGIN
  CREATE ROLE xyz_app NOLOGIN NOBYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------------------------
-- Organisation and permission records
-- ---------------------------------------------------------------------------------------------

CREATE TABLE companies (
  id   text PRIMARY KEY,
  name text NOT NULL
);

CREATE TABLE projects (
  id          text PRIMARY KEY,
  company_id  text NOT NULL REFERENCES companies(id),
  name        text NOT NULL,
  client_name text
);

CREATE TABLE roles (
  name        text PRIMARY KEY,
  scope       text NOT NULL CHECK (scope IN ('assigned', 'company')),
  shared_only boolean NOT NULL DEFAULT false
);

CREATE TABLE doc_types (
  name       text PRIMARY KEY,
  label      text NOT NULL,
  restricted boolean NOT NULL DEFAULT false
);

-- The permissions matrix, as data.
CREATE TABLE role_doc_type_policy (
  role     text NOT NULL REFERENCES roles(name),
  doc_type text NOT NULL REFERENCES doc_types(name),
  PRIMARY KEY (role, doc_type)
);

CREATE TABLE users (
  id            text PRIMARY KEY,
  company_id    text NOT NULL REFERENCES companies(id),
  name          text NOT NULL,
  email         text NOT NULL UNIQUE,
  role          text NOT NULL REFERENCES roles(name),
  organization  text,
  password_hash text,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_members (
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, project_id)
);
CREATE INDEX project_members_project_idx ON project_members (project_id);

-- ---------------------------------------------------------------------------------------------
-- Documents, versions, sections, chunks
-- ---------------------------------------------------------------------------------------------

CREATE TABLE documents (
  id                 text PRIMARY KEY,
  company_id         text NOT NULL REFERENCES companies(id),
  project_id         text REFERENCES projects(id),           -- NULL = company-wide
  doc_type           text NOT NULL REFERENCES doc_types(name),
  title              text NOT NULL,
  -- processing: no version live yet · ready: a version is live · failed: first version failed
  status             text NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
  current_version_id bigint,
  uploaded_by        text REFERENCES users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz                              -- soft delete
);
CREATE INDEX documents_company_project_idx ON documents (company_id, project_id, doc_type);

-- One row per uploaded version. Doubles as the ingestion job queue.
CREATE TABLE document_versions (
  id              bigserial PRIMARY KEY,                       -- monotonic: higher id = newer upload
  document_id     text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_label   text NOT NULL,
  source_text     text NOT NULL,
  source_sha256   text NOT NULL,
  status          text NOT NULL CHECK (status IN ('processing', 'ready', 'failed', 'superseded')),
  attempts        int  NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  locked_until    timestamptz,
  error           text,
  uploaded_by     text REFERENCES users(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  ready_at        timestamptz
);
CREATE INDEX document_versions_queue_idx ON document_versions (next_attempt_at) WHERE status = 'processing';

ALTER TABLE documents
  ADD CONSTRAINT documents_current_version_fk FOREIGN KEY (current_version_id) REFERENCES document_versions(id);

CREATE TABLE document_sections (
  id          bigserial PRIMARY KEY,
  version_id  bigint NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal     int  NOT NULL,
  heading     text NOT NULL,
  visibility  text NOT NULL DEFAULT 'internal' CHECK (visibility IN ('internal', 'client_shared')),
  content     text NOT NULL,
  UNIQUE (version_id, ordinal)
);

-- Chunks carry copies of the fields the permission filter needs (no joins on the hot path).
-- They are only ever changed in the same transaction as their document/section.
CREATE TABLE chunks (
  id          bigserial PRIMARY KEY,
  chunk_key   text NOT NULL,                                   -- e.g. "p001-brd#s4c0"
  version_id  bigint NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  section_id  bigint NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  company_id  text NOT NULL REFERENCES companies(id),
  project_id  text REFERENCES projects(id),
  doc_type    text NOT NULL REFERENCES doc_types(name),
  visibility  text NOT NULL CHECK (visibility IN ('internal', 'client_shared')),
  -- ready: searchable · superseded: older version · deleted: document soft-deleted
  status      text NOT NULL CHECK (status IN ('ready', 'superseded', 'deleted')),
  heading     text NOT NULL,
  content     text NOT NULL,
  token_count int  NOT NULL,
  embedding   vector(1536) NOT NULL,
  UNIQUE (version_id, chunk_key)
);
-- Vector search only ever looks at live chunks.
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops) WHERE status = 'ready';
-- Exact-scan path when the allowed set is small, and the per-document maintenance path.
CREATE INDEX chunks_company_document_idx ON chunks (company_id, document_id);
CREATE INDEX chunks_company_project_type_idx ON chunks (company_id, project_id, doc_type) WHERE status = 'ready';

-- ---------------------------------------------------------------------------------------------
-- Grants and audit
-- ---------------------------------------------------------------------------------------------

CREATE TABLE document_grants (
  id          bigserial PRIMARY KEY,
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  granted_by  text REFERENCES users(id),
  reason      text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz,
  revoked_at  timestamptz
);
CREATE UNIQUE INDEX document_grants_active_uniq ON document_grants (user_id, document_id) WHERE revoked_at IS NULL;

CREATE TABLE audit_log (
  id                  bigserial PRIMARY KEY,
  company_id          text NOT NULL,
  user_id             text NOT NULL,
  query               text NOT NULL,
  retrieved_chunk_ids bigint[] NOT NULL DEFAULT '{}',
  outcome             text NOT NULL CHECK (outcome IN ('answered', 'no_authorized_content')),
  at                  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_user_at_idx ON audit_log (user_id, at DESC);

-- ---------------------------------------------------------------------------------------------
-- Row-level security: the second guard.
-- The application already filters by AccessScope; RLS re-derives the same rule from the database's
-- own permission tables, using only the user id set per transaction (SET LOCAL app.user_id).
-- No user id set → no rows.
-- ---------------------------------------------------------------------------------------------

CREATE FUNCTION app_can_read(p_company text, p_project text, p_document text, p_doc_type text, p_visibility text)
RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM users u
    JOIN roles r ON r.name = u.role
    WHERE u.id = current_setting('app.user_id', true)
      AND u.is_active
      AND u.company_id = p_company
      AND (NOT r.shared_only OR p_visibility = 'client_shared')
      AND (
        (
          EXISTS (SELECT 1 FROM role_doc_type_policy p WHERE p.role = u.role AND p.doc_type = p_doc_type)
          AND (
            r.scope = 'company'
            OR EXISTS (SELECT 1 FROM project_members m WHERE m.user_id = u.id AND m.project_id = p_project)
          )
        )
        OR EXISTS (
          SELECT 1 FROM document_grants g
          WHERE g.user_id = u.id AND g.document_id = p_document
            AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now())
        )
      )
  )
$$;

ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY chunks_read ON chunks FOR SELECT TO xyz_app
  USING (status = 'ready' AND app_can_read(company_id, project_id, document_id, doc_type, visibility));

-- Sections need their document's metadata, and the documents policy needs sections. Reading
-- documents through this definer function (which skips the documents policy) breaks the
-- policy recursion.
CREATE FUNCTION app_doc_meta(p_document text)
RETURNS TABLE (company_id text, project_id text, doc_type text, current_version_id bigint, deleted_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT company_id, project_id, doc_type, current_version_id, deleted_at FROM documents WHERE id = p_document
$$;
REVOKE ALL ON FUNCTION app_doc_meta(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_doc_meta(text) TO xyz_app;

ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;
CREATE POLICY sections_read ON document_sections FOR SELECT TO xyz_app
  USING (EXISTS (
    SELECT 1 FROM app_doc_meta(document_sections.document_id) d
    WHERE d.current_version_id = document_sections.version_id
      AND d.deleted_at IS NULL
      AND app_can_read(d.company_id, d.project_id, document_sections.document_id, d.doc_type,
                       document_sections.visibility)
  ));

-- A document's existence/title is visible only if at least one of its live sections is.
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY documents_read ON documents FOR SELECT TO xyz_app
  USING (deleted_at IS NULL AND EXISTS (
    SELECT 1 FROM document_sections s
    WHERE s.version_id = documents.current_version_id
      AND app_can_read(documents.company_id, documents.project_id, documents.id, documents.doc_type, s.visibility)
  ));

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_insert ON audit_log FOR INSERT TO xyz_app
  WITH CHECK (user_id = current_setting('app.user_id', true));

-- xyz_app: read content (filtered by RLS) and permission records; append to audit log; nothing else.
GRANT SELECT ON companies, projects, roles, doc_types, role_doc_type_policy, users, project_members,
                document_grants, documents, document_sections, chunks TO xyz_app;
GRANT INSERT ON audit_log TO xyz_app;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO xyz_app;
