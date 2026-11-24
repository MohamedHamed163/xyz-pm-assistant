-- Conversational replies (greetings, profile questions, general talk) get their own audit outcome.
ALTER TABLE audit_log DROP CONSTRAINT audit_log_outcome_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_outcome_check CHECK (outcome IN (
  'answered',               -- grounded answer with valid citations
  'chat',                   -- conversational reply, no sources
  'no_authorized_content',  -- (legacy) nothing at all the user may read
  'out_of_scope_project',   -- question names only projects the user cannot access
  'below_relevance',        -- (legacy) authorized chunks exist but none are close enough
  'not_in_context',         -- about XYZ, but the permitted passages don't answer it
  'llm_error'               -- the LLM call failed or returned malformed output
));
