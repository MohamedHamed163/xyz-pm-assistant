"""Document ingestion (design decision 7).

Flow:
  submit_document()  → validates, creates a document_versions row with status 'processing' (the job)
  process_next()     → a worker claims one job, embeds outside any transaction, then swaps it live
                       in ONE transaction (all chunks or none; old version superseded atomically)

Guarantees:
- Only chunks with status 'ready' are searchable; a half-processed version is never visible.
- Embedding failures retry with backoff, up to MAX_ATTEMPTS, then the version is marked 'failed'.
  A previously live version stays live.
- Uploads of the same document serialize on a row lock (SELECT ... FOR UPDATE on documents).
- If an older version finishes after a newer one went live, it is marked 'superseded', never swapped in.
- A worker that crashes leaves a lock that expires (locked_until), so another worker picks the job up.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import psycopg

from .db import to_vector
from .documents import Chunk, Document, DocumentParseError, Section, chunk_document, parse_document
from .embeddings import Embedder

MAX_ATTEMPTS = 3
LOCK_SECONDS = 300


class IngestionError(ValueError):
    pass


@dataclass(frozen=True)
class JobResult:
    version_id: int
    document_id: str
    outcome: str            # 'ready' | 'retry' | 'failed' | 'superseded'
    error: str | None = None


# ---------------------------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------------------------

def submit_document(conn: psycopg.Connection, source_text: str, *, uploaded_by: str | None,
                    company_id: str = "xyz") -> int:
    """Validate a document and queue it for ingestion. Returns the new version id."""
    try:
        doc = parse_document(source_text, company_id=company_id)
    except DocumentParseError as exc:
        raise IngestionError(str(exc)) from exc
    sha = hashlib.sha256(source_text.encode()).hexdigest()

    with conn.transaction():
        # Insert-if-missing first: FOR UPDATE cannot lock a row that doesn't exist yet, so two
        # concurrent first uploads would otherwise both try to INSERT and one would fail.
        conn.execute(
            """INSERT INTO documents (id, company_id, project_id, doc_type, title, status, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, 'processing', %s)
               ON CONFLICT (id) DO NOTHING""",
            (doc.id, company_id, doc.project_id, doc.doc_type, doc.title, uploaded_by),
        )
        row = conn.execute(
            "SELECT project_id, doc_type FROM documents WHERE id = %s FOR UPDATE", (doc.id,)
        ).fetchone()
        if (row[0], row[1]) != (doc.project_id, doc.doc_type):
            raise IngestionError(
                f"{doc.id}: a new version cannot change project or document type "
                f"({row[0]}/{row[1]} → {doc.project_id}/{doc.doc_type}); move the document explicitly"
            )
        (version_id,) = conn.execute(
            """INSERT INTO document_versions (document_id, version_label, source_text, source_sha256, status, uploaded_by)
               VALUES (%s, %s, %s, %s, 'processing', %s) RETURNING id""",
            (doc.id, doc.version, source_text, sha, uploaded_by),
        ).fetchone()
    return version_id


# ---------------------------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------------------------

def process_next(conn: psycopg.Connection, embedder: Embedder) -> JobResult | None:
    """Claim and process one queued version. Returns None when the queue is empty."""
    with conn.transaction():
        row = conn.execute(
            """SELECT id FROM document_versions
               WHERE status = 'processing' AND next_attempt_at <= now()
                 AND (locked_until IS NULL OR locked_until < now())
               ORDER BY id
               LIMIT 1
               FOR UPDATE SKIP LOCKED"""
        ).fetchone()
        if row is None:
            return None
        version_id = row[0]
        conn.execute(
            """UPDATE document_versions
               SET attempts = attempts + 1, locked_until = now() + make_interval(secs => %s)
               WHERE id = %s""",
            (LOCK_SECONDS, version_id),
        )
    return process_version(conn, version_id, embedder)


def run_worker_until_empty(conn: psycopg.Connection, embedder: Embedder) -> list[JobResult]:
    results = []
    while (result := process_next(conn, embedder)) is not None:
        results.append(result)
        if result.outcome == "retry":
            break  # backoff: the job is not due yet; a real worker would sleep and loop
    return results


def process_version(conn: psycopg.Connection, version_id: int, embedder: Embedder) -> JobResult:
    document_id, source_text, attempts, company_id, source_kind = conn.execute(
        """SELECT v.document_id, v.source_text, v.attempts, d.company_id, v.source_kind
           FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE v.id = %s""",
        (version_id,),
    ).fetchone()

    # 1. Parse + chunk + embed — slow, network-bound, outside any transaction.
    #    Markdown sources are parsed here; uploaded files already have reviewed sections in the DB.
    section_ids = None
    try:
        if source_kind == "markdown":
            doc = parse_document(source_text, company_id=company_id)
        else:
            doc, section_ids = _document_from_sections(conn, version_id)
        chunks = chunk_document(doc)
    except DocumentParseError as exc:
        return _record_failure(conn, version_id, document_id, str(exc), attempts, retryable=False)
    try:
        embeddings = embedder.embed([c.text for c in chunks]) if chunks else []
        if len(embeddings) != len(chunks):
            raise RuntimeError(f"embedder returned {len(embeddings)} vectors for {len(chunks)} chunks")
    except Exception as exc:
        return _record_failure(conn, version_id, document_id, f"embedding failed: {exc}", attempts)

    # 2. Swap live — one transaction.
    try:
        with conn.transaction():
            return _swap_in(conn, version_id, doc, chunks, embeddings, section_ids)
    except Exception as exc:
        return _record_failure(conn, version_id, document_id, f"save failed: {exc}", attempts)


def _swap_in(conn, version_id: int, doc: Document, chunks: list[Chunk], embeddings,
             section_ids: dict[int, int] | None = None) -> JobResult:
    current_version_id, deleted_at = conn.execute(
        "SELECT current_version_id, deleted_at FROM documents WHERE id = %s FOR UPDATE", (doc.id,)
    ).fetchone()
    status = conn.execute(
        "SELECT status FROM document_versions WHERE id = %s FOR UPDATE", (version_id,)
    ).fetchone()[0]
    if status != "processing":
        return JobResult(version_id, doc.id, status)

    if current_version_id is not None and current_version_id > version_id:
        conn.execute(
            "UPDATE document_versions SET status = 'superseded', locked_until = NULL WHERE id = %s",
            (version_id,),
        )
        return JobResult(version_id, doc.id, "superseded")

    if section_ids is None:
        section_ids = _insert_sections(conn, version_id, doc)
    live_status = "deleted" if deleted_at is not None else "ready"
    _insert_chunks(conn, version_id, doc, chunks, embeddings, section_ids, live_status)

    if current_version_id is not None:
        conn.execute("UPDATE chunks SET status = 'superseded' WHERE version_id = %s", (current_version_id,))
        conn.execute("UPDATE document_versions SET status = 'superseded' WHERE id = %s", (current_version_id,))
    conn.execute(
        """UPDATE document_versions SET status = 'ready', ready_at = now(), locked_until = NULL, error = NULL
           WHERE id = %s""",
        (version_id,),
    )
    conn.execute(
        """UPDATE documents SET current_version_id = %s, status = 'ready', title = %s, updated_at = now()
           WHERE id = %s""",
        (version_id, doc.title, doc.id),
    )
    return JobResult(version_id, doc.id, "ready")


def _document_from_sections(conn, version_id: int) -> tuple[Document, dict[int, int]]:
    """Build a Document from an uploaded version's reviewed sections (already in the DB)."""
    doc_id, title, project_id, doc_type, company_id = conn.execute(
        """SELECT d.id, d.title, d.project_id, d.doc_type, d.company_id
           FROM document_versions v JOIN documents d ON d.id = v.document_id WHERE v.id = %s""",
        (version_id,),
    ).fetchone()
    rows = conn.execute(
        """SELECT id, ordinal, heading, visibility, content FROM document_sections
           WHERE version_id = %s ORDER BY ordinal""",
        (version_id,),
    ).fetchall()
    sections = tuple(Section(ordinal, heading, visibility, content) for _, ordinal, heading, visibility, content in rows)
    doc = Document(doc_id, title, project_id, doc_type, "", company_id=company_id, sections=sections)
    return doc, {ordinal: sid for sid, ordinal, *_ in rows}


def _insert_sections(conn, version_id: int, doc: Document) -> dict[int, int]:
    ids = {}
    for s in doc.sections:
        (sid,) = conn.execute(
            """INSERT INTO document_sections (version_id, document_id, ordinal, heading, visibility, content)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (version_id, doc.id, s.ordinal, s.heading, s.visibility, s.content),
        ).fetchone()
        ids[s.ordinal] = sid
    return ids


def _insert_chunks(conn, version_id, doc, chunks, embeddings, section_ids, status) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO chunks (chunk_key, version_id, section_id, document_id, company_id, project_id,
                                   doc_type, visibility, status, heading, content, token_count, embedding)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)""",
            [
                (c.id, version_id, section_ids[c.section_ordinal], c.document_id, c.company_id, c.project_id,
                 c.doc_type, c.visibility, status, c.heading, c.text, max(1, len(c.text) // 4), to_vector(e))
                for c, e in zip(chunks, embeddings)
            ],
        )


def _record_failure(conn, version_id: int, document_id: str, error: str, attempts: int,
                    *, retryable: bool = True) -> JobResult:
    final = not retryable or attempts >= MAX_ATTEMPTS
    with conn.transaction():
        if final:
            conn.execute(
                "UPDATE document_versions SET status = 'failed', error = %s, locked_until = NULL WHERE id = %s",
                (error, version_id),
            )
            # Only a document with no live version is marked failed; otherwise the old version stays live.
            conn.execute(
                "UPDATE documents SET status = 'failed', updated_at = now() WHERE id = %s AND current_version_id IS NULL",
                (document_id,),
            )
        else:
            conn.execute(
                """UPDATE document_versions
                   SET error = %s, locked_until = NULL,
                       next_attempt_at = now() + make_interval(secs => power(2, attempts)::int)
                   WHERE id = %s""",
                (error, version_id),
            )
    return JobResult(version_id, document_id, "failed" if final else "retry", error)


# ---------------------------------------------------------------------------------------------
# Soft delete / restore
# ---------------------------------------------------------------------------------------------

def soft_delete_document(conn: psycopg.Connection, document_id: str) -> None:
    with conn.transaction():
        conn.execute("SELECT 1 FROM documents WHERE id = %s FOR UPDATE", (document_id,))
        conn.execute("UPDATE documents SET deleted_at = now(), updated_at = now() WHERE id = %s", (document_id,))
        conn.execute("UPDATE chunks SET status = 'deleted' WHERE document_id = %s AND status = 'ready'", (document_id,))


def restore_document(conn: psycopg.Connection, document_id: str) -> None:
    with conn.transaction():
        (current,) = conn.execute(
            "SELECT current_version_id FROM documents WHERE id = %s FOR UPDATE", (document_id,)
        ).fetchone()
        conn.execute("UPDATE documents SET deleted_at = NULL, updated_at = now() WHERE id = %s", (document_id,))
        conn.execute(
            "UPDATE chunks SET status = 'ready' WHERE version_id = %s AND status = 'deleted'", (current,)
        )
