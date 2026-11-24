-- Three section visibility levels (upload-feature design, Q1/Q5):
--   client_shared (1) < team (2) < management (3)
-- A role sees sections up to its max_visibility; a grant carries its own max_visibility;
-- shared_only roles (clients) never see beyond client_shared, whatever a grant says.

CREATE FUNCTION vis_rank(v text) RETURNS int
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE v WHEN 'client_shared' THEN 1 WHEN 'team' THEN 2 WHEN 'management' THEN 3 END
$$;

-- Roles: highest level each role can see.
ALTER TABLE roles ADD COLUMN max_visibility text NOT NULL DEFAULT 'team'
  CHECK (max_visibility IN ('client_shared', 'team', 'management'));
UPDATE roles SET max_visibility = CASE name
  WHEN 'ceo' THEN 'management' WHEN 'pm' THEN 'management' WHEN 'client' THEN 'client_shared' ELSE 'team' END;

-- Grants: each carries its own level (default team).
ALTER TABLE document_grants ADD COLUMN max_visibility text NOT NULL DEFAULT 'team'
  CHECK (max_visibility IN ('client_shared', 'team', 'management'));

-- Sections and chunks: internal → team; new value set.
ALTER TABLE document_sections DROP CONSTRAINT document_sections_visibility_check;
UPDATE document_sections SET visibility = 'team' WHERE visibility = 'internal';
ALTER TABLE document_sections ALTER COLUMN visibility SET DEFAULT 'team';
ALTER TABLE document_sections ADD CONSTRAINT document_sections_visibility_check
  CHECK (visibility IN ('client_shared', 'team', 'management'));
ALTER TABLE document_sections ADD COLUMN visibility_set_by text REFERENCES users(id);
ALTER TABLE document_sections ADD COLUMN visibility_set_at timestamptz;

ALTER TABLE chunks DROP CONSTRAINT chunks_visibility_check;
UPDATE chunks SET visibility = 'team' WHERE visibility = 'internal';
ALTER TABLE chunks ADD CONSTRAINT chunks_visibility_check
  CHECK (visibility IN ('client_shared', 'team', 'management'));

-- The RLS rule, now level-aware.
CREATE OR REPLACE FUNCTION app_can_read(p_company text, p_project text, p_document text, p_doc_type text, p_visibility text)
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
          vis_rank(p_visibility) <= vis_rank(r.max_visibility)
          AND EXISTS (SELECT 1 FROM role_doc_type_policy p WHERE p.role = u.role AND p.doc_type = p_doc_type)
          AND (
            r.scope = 'company'
            OR EXISTS (SELECT 1 FROM project_members m WHERE m.user_id = u.id AND m.project_id = p_project)
          )
        )
        OR EXISTS (
          SELECT 1 FROM document_grants g
          WHERE g.user_id = u.id AND g.document_id = p_document
            AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now())
            AND vis_rank(p_visibility) <= vis_rank(g.max_visibility)
        )
      )
  )
$$;
