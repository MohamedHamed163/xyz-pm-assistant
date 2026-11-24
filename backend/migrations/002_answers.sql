-- Stage 3: answer generation.

-- Names people use for each project, so a question that names a project the user cannot access
-- can be answered neutrally without retrieval.
ALTER TABLE projects ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';

-- Richer audit outcomes + which retrieved chunks the answer actually cited.
ALTER TABLE audit_log DROP CONSTRAINT audit_log_outcome_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_outcome_check CHECK (outcome IN (
  'answered',               -- grounded answer with valid citations
  'no_authorized_content',  -- nothing at all the user may read
  'out_of_scope_project',   -- question names only projects the user cannot access
  'below_relevance',        -- authorized chunks exist but none are close enough
  'not_in_context',         -- the LLM found no answer in the retrieved passages
  'llm_error'               -- the LLM call failed or returned malformed output
));
ALTER TABLE audit_log ADD COLUMN cited_chunk_ids bigint[] NOT NULL DEFAULT '{}';
ALTER TABLE audit_log ADD COLUMN mentioned_projects text[] NOT NULL DEFAULT '{}';
