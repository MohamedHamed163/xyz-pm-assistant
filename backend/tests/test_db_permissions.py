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

from .conftest import NOW

USERS = ["u-hamed", "u-sara", "u-omar", "u-youssef", "u-mona", "u-amina", "u-khaled"]
EMB = HashingEmbedder()


def python_keys(company, chunks, user_id):
    scope = build_scope(company.users[user_id], company.role_policies, company.grants, now=NOW)
    return {c.id for c in filter_chunks(scope, chunks)}


def sql_keys(db, user_id):
    result = retrieve(db, user_id, "anything", EMB, k=10_000, audit=False)
    return {c.chunk_key for c in result.chunks}


def rls_only_keys(db, user_id, table="chunks", column="chunk_key"):
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
    assert rls_only_keys(db, user_id) == python_keys(company, chunks, user_id)


def test_rls_blocks_everything_without_a_user_id(db):
    assert rls_only_keys(db, None) == set()
    assert rls_only_keys(db, None, "documents", "id") == set()
    assert rls_only_keys(db, None, "document_sections", "id") == set()


def test_rls_still_protects_when_application_filter_is_broken(db, company, chunks, monkeypatch):
    """Simulate a bug that drops the application WHERE clause entirely."""
    monkeypatch.setattr(AccessScope, "to_sql", lambda self, table="chunks": ("TRUE", {}))
    keys = sql_keys(db, "u-sara")
    assert keys == python_keys(company, chunks, "u-sara")
    assert not any(k.startswith("p002") or k.startswith("company") for k in keys)


def test_app_role_cannot_modify_content(db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("SET LOCAL ROLE xyz_app")
            db.execute("UPDATE chunks SET visibility = 'client_shared'")


def test_document_titles_follow_section_visibility(db):
    assert rls_only_keys(db, "u-amina", "documents", "id") == {"p001-brd", "p001-prd", "p001-client-contract"}
    assert "p001-client-contract" not in rls_only_keys(db, "u-sara", "documents", "id")
    assert "company-profitability-2026" not in rls_only_keys(db, "u-hamed", "documents", "id")


def test_amina_sections_are_all_client_shared(db):
    ids = rls_only_keys(db, "u-amina", "document_sections", "id")
    vis = {r[0] for r in db.execute("SELECT visibility FROM document_sections WHERE id = ANY(%s)", (list(ids),))}
    assert vis == {"client_shared"}


def test_sara_p002_question_gets_no_p002_content(db):
    result = retrieve(db, "u-sara", "What is the authentication flow in P002? Shibboleth SAML", EMB, audit=False)
    assert result.chunks
    assert all(c.document_id.startswith("p001") for c in result.chunks)


def test_revoking_a_grant_applies_on_the_next_query(db):
    assert any(k.startswith("p001-client-contract") for k in sql_keys(db, "u-amina"))
    db.execute("UPDATE document_grants SET revoked_at = now() WHERE user_id = 'u-amina'")
    try:
        assert not any(k.startswith("p001-client-contract") for k in sql_keys(db, "u-amina"))
        assert not any(k.startswith("p001-client-contract") for k in rls_only_keys(db, "u-amina"))
    finally:
        db.execute("UPDATE document_grants SET revoked_at = NULL WHERE user_id = 'u-amina'")


def test_expired_grant_is_ignored_by_both_layers(db):
    db.execute("UPDATE document_grants SET expires_at = now() - interval '1 minute' WHERE user_id = 'u-khaled'")
    try:
        assert sql_keys(db, "u-khaled") == set()
        assert rls_only_keys(db, "u-khaled") == set()
    finally:
        db.execute("UPDATE document_grants SET expires_at = NULL WHERE user_id = 'u-khaled'")


def test_project_reassignment_applies_on_the_next_query(db):
    db.execute("UPDATE project_members SET project_id = 'P002' WHERE user_id = 'u-hamed'")
    try:
        keys = sql_keys(db, "u-hamed")
        assert keys and all(k.startswith("p002") for k in keys)
        assert rls_only_keys(db, "u-hamed") == keys
    finally:
        db.execute("UPDATE project_members SET project_id = 'P001' WHERE user_id = 'u-hamed'")


def test_deactivated_user_sees_nothing_and_is_audited(db):
    db.execute("UPDATE users SET is_active = false WHERE id = 'u-omar'")
    try:
        result = retrieve(db, "u-omar", "What are the open bugs?", EMB)
        assert result.chunks == [] and result.outcome == "no_authorized_content"
        assert rls_only_keys(db, "u-omar") == set()
        outcome = db.execute(
            "SELECT outcome FROM audit_log WHERE user_id = 'u-omar' ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert outcome == "no_authorized_content"
    finally:
        db.execute("UPDATE users SET is_active = true WHERE id = 'u-omar'")


def test_audit_log_records_retrieved_chunk_ids(db):
    result = retrieve(db, "u-sara", "authentication flow refresh token", EMB, k=3)
    row = db.execute(
        "SELECT query, retrieved_chunk_ids, outcome FROM audit_log WHERE user_id = 'u-sara' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ("authentication flow refresh token", [c.id for c in result.chunks], "answered")


def test_load_scope_from_db_matches_seed_scope(db, company):
    for uid in USERS:
        from_db = load_scope(db, uid, now=NOW)
        from_seed = build_scope(company.users[uid], company.role_policies, company.grants, now=NOW)
        assert from_db == from_seed, uid


def test_unknown_user_is_rejected(db):
    with pytest.raises(LookupError):
        retrieve(db, "u-nobody", "hello", EMB)


def test_retrieval_fills_k_for_selective_filter(db):
    """Iterative HNSW scan: Amina can read few chunks, but k should still be filled up to that count."""
    allowed = len(sql_keys(db, "u-amina"))
    k = min(5, allowed)
    result = retrieve(db, "u-amina", "payment", EMB, k=k, audit=False)
    assert len(result.chunks) == k
    assert [c.distance for c in result.chunks] == sorted(c.distance for c in result.chunks)
