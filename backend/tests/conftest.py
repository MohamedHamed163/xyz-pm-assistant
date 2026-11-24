import os
import tempfile
from datetime import datetime, timezone

# Tests drive the workers themselves and must never touch the dev database or real storage.
os.environ["WORKER_IN_PROCESS"] = "false"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="xyz-test-storage-")

import pytest  # noqa: E402

from app.documents import chunk_document, load_documents  # noqa: E402
from app.policy import build_scope, filter_chunks  # noqa: E402
from app.seed import DOCUMENTS_DIR, load_company  # noqa: E402

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def company():
    return load_company()


@pytest.fixture(scope="session")
def documents():
    return load_documents(DOCUMENTS_DIR)


@pytest.fixture(scope="session")
def chunks(documents):
    return [c for d in documents for c in chunk_document(d)]


@pytest.fixture(scope="session")
def db():
    """A fresh test database, migrated and seeded with the demo company and all 12 documents."""
    from app.embeddings import HashingEmbedder
    from app.seed_db import seed_all

    from .db_helpers import new_conn, recreate_test_database

    recreate_test_database()
    conn = new_conn()
    results = seed_all(conn, HashingEmbedder())
    assert [r.outcome for r in results] == ["ready"] * 12
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def visible_text(company, chunks):
    """visible_text("Sara") -> all text Sara could ever retrieve, as one string."""

    def _visible(name: str) -> str:
        user = company.user_by_name(name)
        scope = build_scope(user, company.role_policies, company.grants, now=NOW)
        return "\n".join(c.text for c in filter_chunks(scope, chunks))

    return _visible
