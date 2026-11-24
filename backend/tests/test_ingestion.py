"""Ingestion: versions, atomic swaps, retries, crashes, concurrency, soft delete.

Each test uses its own document ids so it does not disturb the seeded demo data.
"""

import pytest

from app import ingestion
from app.embeddings import HashingEmbedder
from app.ingestion import (
    IngestionError,
    process_next,
    process_version,
    restore_document,
    soft_delete_document,
    submit_document,
)
from app.retrieval import retrieve

from .db_helpers import FailingEmbedder, SlowEmbedder, make_doc, new_conn, run_in_threads

EMB = HashingEmbedder()


@pytest.fixture(autouse=True)
def cleanup_test_documents(db):
    yield
    db.execute("DELETE FROM documents WHERE id LIKE 't-%'")


def mona_sees(db, text):
    result = retrieve(db, "u-mona", text, EMB, k=10_000, audit=False)
    return any(text in c.content for c in result.chunks)


def version_status(db, version_id):
    return db.execute("SELECT status FROM document_versions WHERE id = %s", (version_id,)).fetchone()[0]


def drain(db, embedder=EMB):
    while (r := process_next(db, embedder)) is not None:
        pass


def test_new_version_swaps_atomically(db):
    drain(db)
    v1 = submit_document(db, make_doc("t-swap", body="ALPHA-ONE content"), uploaded_by="u-hamed")
    assert not mona_sees(db, "ALPHA-ONE")                       # processing: not searchable
    assert process_next(db, EMB).outcome == "ready"
    assert mona_sees(db, "ALPHA-ONE")

    v2 = submit_document(db, make_doc("t-swap", body="BETA-TWO content", version="2"), uploaded_by="u-hamed")
    assert mona_sees(db, "ALPHA-ONE") and not mona_sees(db, "BETA-TWO")   # v1 stays live meanwhile
    assert process_next(db, EMB).outcome == "ready"
    assert mona_sees(db, "BETA-TWO") and not mona_sees(db, "ALPHA-ONE")
    assert (version_status(db, v1), version_status(db, v2)) == ("superseded", "ready")


def test_older_version_finishing_late_never_overwrites_newer(db):
    drain(db)
    old = submit_document(db, make_doc("t-race", body="OLD-VERSION"), uploaded_by="u-hamed")
    new = submit_document(db, make_doc("t-race", body="NEW-VERSION", version="2"), uploaded_by="u-hamed")
    assert process_version(db, new, EMB).outcome == "ready"
    assert process_version(db, old, EMB).outcome == "superseded"
    assert mona_sees(db, "NEW-VERSION") and not mona_sees(db, "OLD-VERSION")


def test_embedding_failure_retries_then_fails_and_old_version_stays_live(db):
    drain(db)
    submit_document(db, make_doc("t-retry", body="STABLE-V1"), uploaded_by="u-hamed")
    drain(db)
    v2 = submit_document(db, make_doc("t-retry", body="BROKEN-V2", version="2"), uploaded_by="u-hamed")
    failing = FailingEmbedder()
    outcomes = []
    for _ in range(ingestion.MAX_ATTEMPTS):
        db.execute("UPDATE document_versions SET next_attempt_at = now() WHERE id = %s", (v2,))  # skip backoff
        outcomes.append(process_next(db, failing).outcome)
    assert outcomes == ["retry", "retry", "failed"]
    assert version_status(db, v2) == "failed"
    assert mona_sees(db, "STABLE-V1") and not mona_sees(db, "BROKEN-V2")
    assert db.execute("SELECT status FROM documents WHERE id = 't-retry'").fetchone()[0] == "ready"


def test_retry_then_success(db):
    drain(db)
    v = submit_document(db, make_doc("t-flaky", body="EVENTUALLY-OK"), uploaded_by="u-hamed")
    assert process_next(db, FailingEmbedder(fail_times=1)).outcome == "retry"
    assert process_next(db, EMB) is None                         # backoff: not due yet
    db.execute("UPDATE document_versions SET next_attempt_at = now() WHERE id = %s", (v,))
    assert process_next(db, EMB).outcome == "ready"
    assert mona_sees(db, "EVENTUALLY-OK")


def test_first_version_failure_marks_document_failed(db):
    drain(db)
    submit_document(db, make_doc("t-dead", body="NEVER-LIVE"), uploaded_by="u-hamed")
    for _ in range(ingestion.MAX_ATTEMPTS):
        db.execute("UPDATE document_versions SET next_attempt_at = now() WHERE document_id = 't-dead'")
        process_next(db, FailingEmbedder())
    assert db.execute("SELECT status FROM documents WHERE id = 't-dead'").fetchone()[0] == "failed"


def test_crash_mid_save_leaves_no_partial_rows(db, monkeypatch):
    drain(db)
    v = submit_document(db, make_doc("t-crash", body="PARTIAL\n\nsecond para"), uploaded_by="u-hamed")
    original = ingestion._insert_chunks

    def insert_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("simulated crash after inserting chunks")

    monkeypatch.setattr(ingestion, "_insert_chunks", insert_then_crash)
    assert process_next(db, EMB).outcome == "retry"
    counts = db.execute(
        """SELECT (SELECT count(*) FROM chunks WHERE version_id = %(v)s),
                  (SELECT count(*) FROM document_sections WHERE version_id = %(v)s)""", {"v": v}
    ).fetchone()
    assert counts == (0, 0)
    assert version_status(db, v) == "processing"


def test_crashed_worker_lock_expires_and_job_is_reclaimed(db):
    drain(db)
    v = submit_document(db, make_doc("t-lock", body="RECLAIMED"), uploaded_by="u-hamed")
    # A worker claimed the job and died before finishing.
    db.execute("UPDATE document_versions SET attempts = 1, locked_until = now() + interval '5 min' WHERE id = %s", (v,))
    assert process_next(db, EMB) is None
    db.execute("UPDATE document_versions SET locked_until = now() - interval '1 second' WHERE id = %s", (v,))
    assert process_next(db, EMB).outcome == "ready"


def test_concurrent_workers_claim_different_jobs(db):
    drain(db)
    a = submit_document(db, make_doc("t-par-a", body="PAR-A"), uploaded_by="u-hamed")
    b = submit_document(db, make_doc("t-par-b", body="PAR-B"), uploaded_by="u-hamed")
    c1, c2 = new_conn(), new_conn()
    try:
        slow = SlowEmbedder(0.3)
        r1, r2 = run_in_threads(lambda: process_next(c1, slow), lambda: process_next(c2, slow))
    finally:
        c1.close(), c2.close()
    assert {r1.version_id, r2.version_id} == {a, b}
    assert {r1.outcome, r2.outcome} == {"ready"}


def test_concurrent_first_uploads_of_same_document(db):
    drain(db)
    c1, c2 = new_conn(), new_conn()
    try:
        v1, v2 = run_in_threads(
            lambda: submit_document(c1, make_doc("t-dup", body="UP-1"), uploaded_by="u-hamed"),
            lambda: submit_document(c2, make_doc("t-dup", body="UP-2", version="2"), uploaded_by="u-hamed"),
        )
    finally:
        c1.close(), c2.close()
    assert v1 != v2
    drain(db)
    assert db.execute("SELECT count(*) FROM documents WHERE id = 't-dup'").fetchone()[0] == 1
    newest = "UP-2" if v2 > v1 else "UP-1"
    assert mona_sees(db, newest)


def test_soft_delete_hides_immediately_and_restore_brings_it_back(db):
    drain(db)
    submit_document(db, make_doc("t-del", body="DELETE-ME"), uploaded_by="u-hamed")
    drain(db)
    soft_delete_document(db, "t-del")
    assert not mona_sees(db, "DELETE-ME")
    # A new version processed while deleted stays hidden.
    submit_document(db, make_doc("t-del", body="DELETE-ME v2", version="2"), uploaded_by="u-hamed")
    drain(db)
    assert not mona_sees(db, "DELETE-ME")
    restore_document(db, "t-del")
    assert mona_sees(db, "DELETE-ME v2")


def test_new_version_cannot_move_project(db):
    submit_document(db, make_doc("t-move", body="x"), uploaded_by="u-hamed")
    with pytest.raises(IngestionError):
        submit_document(db, make_doc("t-move", body="x", project="P002"), uploaded_by="u-hamed")
    drain(db)


def test_invalid_document_is_rejected_at_upload(db):
    bad = make_doc("t-bad", body="x").replace("## Body", "## Body <!-- visibility: everyone -->")
    with pytest.raises(IngestionError):
        submit_document(db, bad, uploaded_by="u-hamed")
    assert db.execute("SELECT count(*) FROM documents WHERE id = 't-bad'").fetchone()[0] == 0


def test_test_documents_never_leak_into_client_view(db):
    """All test docs above are P001 PRDs with internal sections — Amina must see none of them."""
    drain(db)
    result = retrieve(db, "u-amina", "content", EMB, k=10_000, audit=False)
    assert not any(c.document_id.startswith("t-") for c in result.chunks)
