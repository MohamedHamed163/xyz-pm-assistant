"""Permission enforcement inside Postgres.

Three independent checks must agree for every demo user:
  1. the Python policy (AccessScope.allows) over the parsed documents,
  2. the SQL retrieval path (application WHERE clause + RLS),
  3. row-level security ALONE (no application filter at all).
"""

import psycopg
import pytest

from app.embeddings import HashingEmbedder
from app.policy import AccessScope, build_scope, filter_chunks
from app.retrieval import load_scope, retrieve

USERS = ["u-mona", "u-hamed", "u-sara", "u-omar", "u-khaled", "u-amina", "u-youssef"]
EMB = HashingEmbedder()


def python_keys(company, chunks, user_id):
    scope = build_scope(company.users[user_id], company.role_policies)
    return {c.id for c in filter_chunks(scope, chunks)}


def sql_keys(db, user_id):
    return {c.chunk_key for c in retrieve(db, user_id, "anything", EMB, k=10_000, audit=False).chunks}


def rls_only(db, user_id, table="chunks", column="chunk_key"):
    """Query as xyz_app with NO application filter — only row-level security applies."""
    with db.transaction():
        db.execute("SET LOCAL ROLE xyz_app")
        if user_id is not None:
            db.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
        return {r[0] for r in db.execute(f"SELECT {column} FROM {table}")}


@pytest.mark.parametrize("user_id", USERS)
def test_sql_retrieval_matches_python_policy(db, company, chunks, user_id):
    assert sql_keys(db, user_id) == python_keys(company, chunks, user_id)


@pytest.mark.parametrize("user_id", USERS)
def test_rls_alone_matches_python_policy(db, company, chunks, user_id):
    assert rls_only(db, user_id) == python_keys(company, chunks, user_id)


def test_rls_blocks_everything_without_a_user_id(db):
    assert rls_only(db, None) == set()
    assert rls_only(db, None, "documents", "id") == set()
    assert rls_only(db, None, "document_sections", "id") == set()


def test_rls_still_protects_when_application_filter_is_broken(db, company, chunks, monkeypatch):
    """Simulate a bug that drops the application WHERE clause entirely."""
    monkeypatch.setattr(AccessScope, "to_sql", lambda self, table="chunks": ("TRUE", {}))
    assert sql_keys(db, "u-omar") == python_keys(company, chunks, "u-omar")


def test_app_role_cannot_modify_content(db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("SET LOCAL ROLE xyz_app")
            db.execute("UPDATE chunks SET topic = 'details'")


def test_document_titles_follow_topic_access(db):
    assert rls_only(db, "u-youssef", "documents", "id") == {"hub-brd", "hub-prd", "hub-proposal"}
    assert rls_only(db, "u-sara", "documents", "id") == {"droob-brd", "droob-prd", "droob-proposal"}


def test_rule_change_applies_on_the_next_query_without_reprocessing(db):
    """Let QA read BRD context: one row in role_topic_access, nothing re-embedded."""
    assert not any(k == "droob-brd#s1c0" for k in sql_keys(db, "u-omar"))
    db.execute("INSERT INTO role_topic_access VALUES ('qa', 'brd', 'context')")
    try:
        assert any(k == "droob-brd#s1c0" for k in sql_keys(db, "u-omar"))
        assert any(k == "droob-brd#s1c0" for k in rls_only(db, "u-omar"))
    finally:
        db.execute("DELETE FROM role_topic_access WHERE role = 'qa' AND doc_type = 'brd' AND topic = 'context'")


def test_project_reassignment_applies_on_the_next_query(db):
    db.execute("UPDATE project_members SET project_id = 'P002' WHERE user_id = 'u-sara'")
    try:
        keys = sql_keys(db, "u-sara")
        assert keys and all(k.startswith("hub-") for k in keys)
        assert rls_only(db, "u-sara") == keys
    finally:
        db.execute("UPDATE project_members SET project_id = 'P001' WHERE user_id = 'u-sara'")


def test_deactivated_user_sees_nothing(db):
    db.execute("UPDATE users SET is_active = false WHERE id = 'u-omar'")
    try:
        assert retrieve(db, "u-omar", "rules", EMB).chunks == []
        assert rls_only(db, "u-omar") == set()
    finally:
        db.execute("UPDATE users SET is_active = true WHERE id = 'u-omar'")


def test_load_scope_from_db_matches_seed(db, company):
    for uid in USERS:
        assert load_scope(db, uid) == build_scope(company.users[uid], company.role_policies), uid


def test_unknown_user_is_rejected(db):
    with pytest.raises(LookupError):
        retrieve(db, "u-nobody", "hello", EMB)


def test_retrieval_fills_k_for_a_selective_role(db):
    """Iterative HNSW scan: QA reads few chunks, but k should still be filled up to that count."""
    k = min(5, len(sql_keys(db, "u-omar")))
    result = retrieve(db, "u-omar", "rules", EMB, k=k, audit=False)
    assert len(result.chunks) == k
    assert [c.distance for c in result.chunks] == sorted(c.distance for c in result.chunks)
