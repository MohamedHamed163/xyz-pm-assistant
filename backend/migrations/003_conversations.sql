-- Stage 4: chat history.
-- Conversations belong to exactly one user. The API always filters by the authenticated user id;
-- another user's conversation id returns 404 (same as a missing one).

CREATE TABLE conversations (
  id         bigserial PRIMARY KEY,
  company_id text NOT NULL REFERENCES companies(id),
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      text NOT NULL DEFAULT 'New conversation',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
-- Sidebar listing: newest first, keyset-paginated on (updated_at, id).
CREATE INDEX conversations_user_updated_idx ON conversations (user_id, updated_at DESC, id DESC);

CREATE TABLE messages (
  id              bigserial PRIMARY KEY,
  conversation_id bigint NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user', 'assistant')),
  content         text NOT NULL,
  outcome         text,                         -- assistant only: same values as audit_log.outcome
  citations       jsonb NOT NULL DEFAULT '[]',  -- assistant only: backend-built citation list
  created_at      timestamptz NOT NULL DEFAULT now()
);
-- Thread view: keyset-paginated on (created_at, id) within a conversation.
CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at, id);
