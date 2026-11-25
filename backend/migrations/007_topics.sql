-- Topic-based access (design review 2026-11-25).
-- Access = project membership (CEO: every project) × role_topic_access(role, doc_type, topic).
-- This migration starts the content fresh: all documents, chats, audit and history are removed
-- (a pg_dump backup was taken first — see backups/).

-- 1. Start fresh.
TRUNCATE messages, conversations, audit_log, visibility_changes, chunks, document_sections,
         document_versions, documents, document_grants RESTART IDENTITY CASCADE;
DELETE FROM project_members;
DELETE FROM projects WHERE id NOT IN ('P001', 'P002');

-- 2. Old row-level rules go first (they reference the old columns).
DROP POLICY chunks_read ON chunks;
DROP POLICY sections_read ON document_sections;
DROP POLICY documents_read ON documents;
DROP FUNCTION app_can_read(text, text, text, text, text);
DROP FUNCTION vis_rank(text);

-- 3. Levels, grants and the per-type policy are replaced by topics.
DROP TABLE document_grants;
DROP TABLE role_doc_type_policy;
ALTER TABLE roles DROP COLUMN max_visibility, DROP COLUMN shared_only;
DELETE FROM doc_types;
ALTER TABLE doc_types DROP COLUMN restricted;
INSERT INTO doc_types (name, label) VALUES
  ('brd', 'Business Requirements Document'), ('prd', 'Product Requirements Document'), ('proposal', 'Proposal');

-- 4. Topics and the rules, as data.
CREATE TABLE topics (
  doc_type text NOT NULL REFERENCES doc_types(name) ON DELETE CASCADE,
  key      text NOT NULL,
  label    text NOT NULL,
  ordinal  int  NOT NULL,
  PRIMARY KEY (doc_type, key)
);
CREATE TABLE topic_headings (
  doc_type text NOT NULL,
  keyword  text NOT NULL,
  topic    text NOT NULL,
  PRIMARY KEY (doc_type, keyword),
  FOREIGN KEY (doc_type, topic) REFERENCES topics(doc_type, key) ON DELETE CASCADE
);
CREATE TABLE role_topic_access (
  role     text NOT NULL REFERENCES roles(name) ON DELETE CASCADE,
  doc_type text NOT NULL,
  topic    text NOT NULL,
  PRIMARY KEY (role, doc_type, topic),
  FOREIGN KEY (doc_type, topic) REFERENCES topics(doc_type, key) ON DELETE CASCADE
);

-- 5. Sections and chunks carry a topic; chunks also a combined access key for the filter/index.
ALTER TABLE document_sections DROP COLUMN visibility;
ALTER TABLE document_sections ADD COLUMN topic text NOT NULL DEFAULT 'unclassified';
ALTER TABLE document_sections RENAME COLUMN visibility_set_by TO topic_set_by;
ALTER TABLE document_sections RENAME COLUMN visibility_set_at TO topic_set_at;

ALTER TABLE chunks DROP COLUMN visibility;
ALTER TABLE chunks ADD COLUMN topic text NOT NULL;
ALTER TABLE chunks ADD COLUMN access_key text GENERATED ALWAYS AS (doc_type || ':' || topic) STORED;
DROP INDEX chunks_company_project_type_idx;
CREATE INDEX chunks_access_idx ON chunks (company_id, project_id, access_key) WHERE status = 'ready';

-- 6. History: topic changes (publish, live fixes, restore) and membership changes.
ALTER TABLE visibility_changes RENAME TO topic_changes;
ALTER TABLE topic_changes RENAME COLUMN old_visibility TO old_topic;
ALTER TABLE topic_changes RENAME COLUMN new_visibility TO new_topic;
ALTER INDEX visibility_changes_document_idx RENAME TO topic_changes_document_idx;

CREATE TABLE membership_changes (
  id         bigserial PRIMARY KEY,
  project_id text REFERENCES projects(id) ON DELETE CASCADE,       -- NULL for role changes
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action     text NOT NULL CHECK (action IN ('add', 'remove', 'role_change', 'project_created')),
  detail     text,
  changed_by text NOT NULL REFERENCES users(id),
  changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX membership_changes_project_idx ON membership_changes (project_id, changed_at DESC);

-- 7. Drafts: optimistic lock so two reviewers never overwrite each other silently.
ALTER TABLE document_versions ADD COLUMN lock_version int NOT NULL DEFAULT 0;
ALTER TABLE document_versions ADD COLUMN edited_by text REFERENCES users(id);

-- 8. The RLS rule, now topic-based.
CREATE FUNCTION app_can_read(p_company text, p_project text, p_document text, p_doc_type text, p_topic text)
RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM users u
    JOIN roles r ON r.name = u.role
    WHERE u.id = current_setting('app.user_id', true)
      AND u.is_active
      AND u.company_id = p_company
      AND (r.scope = 'company'
           OR EXISTS (SELECT 1 FROM project_members m WHERE m.user_id = u.id AND m.project_id = p_project))
      AND EXISTS (SELECT 1 FROM role_topic_access a
                  WHERE a.role = u.role AND a.doc_type = p_doc_type AND a.topic = p_topic)
  )
$$;

CREATE POLICY chunks_read ON chunks FOR SELECT TO xyz_app
  USING (status = 'ready' AND app_can_read(company_id, project_id, document_id, doc_type, topic));

CREATE POLICY sections_read ON document_sections FOR SELECT TO xyz_app
  USING (EXISTS (
    SELECT 1 FROM app_doc_meta(document_sections.document_id) d
    WHERE d.current_version_id = document_sections.version_id
      AND d.deleted_at IS NULL
      AND app_can_read(d.company_id, d.project_id, document_sections.document_id, d.doc_type,
                       document_sections.topic)
  ));

CREATE POLICY documents_read ON documents FOR SELECT TO xyz_app
  USING (deleted_at IS NULL AND EXISTS (
    SELECT 1 FROM document_sections s
    WHERE s.version_id = documents.current_version_id
      AND app_can_read(documents.company_id, documents.project_id, documents.id, documents.doc_type, s.topic)
  ));

GRANT SELECT ON topics, topic_headings, role_topic_access TO xyz_app;
