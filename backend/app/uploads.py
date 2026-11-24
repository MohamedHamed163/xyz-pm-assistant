"""Upload → parse → draft review → publish (upload-feature design Q3–Q9).

Permissions (Q3) — enforced here, never only in the UI:
  CEO: any document type, any project or company-wide.
  PM:  standard (non-restricted) types, only in projects they are assigned to.
  Everyone else: no uploads.
The same rule decides who may manage an existing document (new versions, live visibility edits,
restore). Permissions are re-checked at publish time (Q8).

Drafts are invisible to search: no chunks exist until publish, and section RLS only exposes a
document's CURRENT version. Only the uploader and the CEO can see a draft or download an original.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import psycopg

from .parsing import ParseError, detect_kind, parse_file_isolated
from .policy import LEVELS, RANK
from .storage import LocalStorage, TooLarge

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PARSING_PER_USER = 5
DRAFT_DAYS = 7
MAX_SECTIONS = 500
LOCK_SECONDS = 300


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    company_id: str


def load_actor(conn, user_id: str) -> Actor:
    row = conn.execute("SELECT id, role, company_id FROM users WHERE id = %s AND is_active", (user_id,)).fetchone()
    if row is None:
        raise UploadError(401, "Not authenticated")
    return Actor(*row)


# ---------------------------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------------------------

def _restricted_types(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM doc_types WHERE restricted")}


def can_upload(conn, actor: Actor, project_id: str | None, doc_type: str) -> bool:
    if conn.execute("SELECT 1 FROM doc_types WHERE name = %s", (doc_type,)).fetchone() is None:
        return False
    if project_id is not None and conn.execute(
            "SELECT 1 FROM projects WHERE id = %s AND company_id = %s", (project_id, actor.company_id)).fetchone() is None:
        return False
    if actor.role == "ceo":
        return True
    if actor.role == "pm":
        return (project_id is not None and doc_type not in _restricted_types(conn)
                and conn.execute("SELECT 1 FROM project_members WHERE user_id = %s AND project_id = %s",
                                 (actor.id, project_id)).fetchone() is not None)
    return False


def upload_options(conn, actor: Actor) -> dict:
    projects = conn.execute("SELECT id, name FROM projects WHERE company_id = %s ORDER BY id",
                            (actor.company_id,)).fetchall()
    types = conn.execute("SELECT name, label, restricted FROM doc_types ORDER BY name").fetchall()
    allowed_projects = [{"id": p, "name": n} for p, n in projects if any(can_upload(conn, actor, p, t) for t, *_ in types)]
    allowed_types = [{"name": t, "label": l} for t, l, r in types if actor.role == "ceo" or (actor.role == "pm" and not r)]
    return {
        "can_upload": bool(allowed_projects) or actor.role == "ceo",
        "projects": allowed_projects,
        "company_wide": actor.role == "ceo",
        "doc_types": allowed_types,
        "levels": list(LEVELS),
    }


def _manageable_document(conn, actor: Actor, document_id: str, *, lock: bool = False):
    row = conn.execute(
        f"""SELECT id, project_id, doc_type, current_version_id, company_id, title, deleted_at
            FROM documents WHERE id = %s {'FOR UPDATE' if lock else ''}""",
        (document_id,),
    ).fetchone()
    if row is None or row[4] != actor.company_id or not can_upload(conn, actor, row[1], row[2]):
        raise UploadError(404, "Document not found")      # same answer for missing and not permitted
    return row


# ---------------------------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------------------------

def create_upload(conn, storage: LocalStorage, actor: Actor, stream: BinaryIO, file_name: str, *,
                  doc_type: str | None = None, project_id: str | None = None, title: str | None = None,
                  document_id: str | None = None) -> int:
    """Store the file and queue it for parsing. Returns the new version id."""
    if document_id is None:
        if not doc_type or not can_upload(conn, actor, project_id, doc_type):
            raise UploadError(403, "You can't upload this document type to this project.")
    else:
        _, project_id, doc_type, *_ = _manageable_document(conn, actor, document_id)

    in_flight = conn.execute(
        "SELECT count(*) FROM document_versions WHERE drafted_by = %s AND status = 'parsing'", (actor.id,)
    ).fetchone()[0]
    if in_flight >= MAX_PARSING_PER_USER:
        raise UploadError(429, f"You already have {MAX_PARSING_PER_USER} files being parsed. Try again in a moment.")

    try:
        key, size, _ = storage.put_stream(stream, max_bytes=MAX_UPLOAD_BYTES)
    except TooLarge:
        raise UploadError(413, "Files can be at most 20 MB.")
    try:
        kind = detect_kind(storage.path(key))
    except ParseError as exc:
        _unlink_if_unused(conn, storage, key)
        raise UploadError(400, str(exc))

    clean_name = Path(file_name or "upload").name[:200]
    with conn.transaction():
        if document_id is None:
            title = (title or Path(clean_name).stem).strip()[:200] or "Untitled document"
            document_id = _new_document_id(project_id, title)
            conn.execute(
                """INSERT INTO documents (id, company_id, project_id, doc_type, title, status, uploaded_by)
                   VALUES (%s, %s, %s, %s, %s, 'processing', %s)""",
                (document_id, actor.company_id, project_id, doc_type, title, actor.id),
            )
            base = None
        else:
            base = conn.execute("SELECT current_version_id FROM documents WHERE id = %s FOR UPDATE",
                                (document_id,)).fetchone()[0]
        label = conn.execute("SELECT count(*) + 1 FROM document_versions WHERE document_id = %s",
                             (document_id,)).fetchone()[0]
        (version_id,) = conn.execute(
            """INSERT INTO document_versions
                 (document_id, version_label, source_sha256, status, source_kind, file_key, file_name,
                  file_size, base_version_id, drafted_by, uploaded_by)
               VALUES (%s, %s, %s, 'parsing', %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (document_id, str(label), key, kind, key, clean_name, size, base, actor.id, actor.id),
        ).fetchone()
    return version_id


def _new_document_id(project_id: str | None, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "document"
    return f"{(project_id or 'company').lower()}-{slug}-{secrets.token_hex(3)}"


def _unlink_if_unused(conn, storage: LocalStorage, key: str) -> None:
    if conn.execute("SELECT 1 FROM document_versions WHERE file_key = %s LIMIT 1", (key,)).fetchone() is None:
        storage.path(key).unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------------
# Parse worker
# ---------------------------------------------------------------------------------------------

def parse_next(conn, storage: LocalStorage) -> tuple[int, str] | None:
    """Claim one 'parsing' version, parse it in an isolated process, turn it into a draft."""
    with conn.transaction():
        row = conn.execute(
            """SELECT id, file_key, source_kind, document_id, base_version_id FROM document_versions
               WHERE status = 'parsing' AND (locked_until IS NULL OR locked_until < now())
               ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"""
        ).fetchone()
        if row is None:
            return None
        version_id, key, kind, document_id, base = row
        conn.execute("UPDATE document_versions SET attempts = attempts + 1, "
                     "locked_until = now() + make_interval(secs => %s) WHERE id = %s", (LOCK_SECONDS, version_id))
    try:
        parsed = parse_file_isolated(storage.path(key), kind)
    except ParseError as exc:
        with conn.transaction():
            conn.execute("UPDATE document_versions SET status = 'failed', error = %s, locked_until = NULL "
                         "WHERE id = %s", (str(exc), version_id))
        return version_id, "failed"

    previous = _levels_by_heading(conn, base)
    with conn.transaction():
        for n, s in enumerate(parsed.sections):
            conn.execute(
                """INSERT INTO document_sections (version_id, document_id, ordinal, heading, visibility, content)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (version_id, document_id, n, s.heading[:200], previous.get(_norm(s.heading), "team"), s.content),
            )
        conn.execute(
            """UPDATE document_versions SET status = 'draft', locked_until = NULL, error = NULL, page_count = %s,
                 source_text = %s, draft_expires_at = now() + make_interval(days => %s) WHERE id = %s""",
            (parsed.page_count, "\n\n".join(f"## {s.heading}\n\n{s.content}" for s in parsed.sections),
             DRAFT_DAYS, version_id),
        )
    return version_id, "draft"


def _norm(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()


def _levels_by_heading(conn, version_id: int | None) -> dict[str, str]:
    if version_id is None:
        return {}
    return {_norm(h): v for h, v in conn.execute(
        "SELECT heading, visibility FROM document_sections WHERE version_id = %s", (version_id,))}


# ---------------------------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------------------------

def _own_version(conn, actor: Actor, version_id: int, *, lock: bool = False):
    row = conn.execute(
        f"""SELECT v.id, v.document_id, v.status, v.drafted_by, v.base_version_id, v.draft_expires_at,
                   v.error, v.file_name, v.file_size, v.page_count, v.source_kind, v.file_key, v.created_at,
                   d.title, d.project_id, d.doc_type, d.company_id, v.published_at
            FROM document_versions v JOIN documents d ON d.id = v.document_id
            WHERE v.id = %s AND v.drafted_by IS NOT NULL {'FOR UPDATE OF v' if lock else ''}""",
        (version_id,),
    ).fetchone()
    if row is None or row[16] != actor.company_id or not (row[3] == actor.id or actor.role == "ceo"):
        raise UploadError(404, "Upload not found")
    return row


def get_upload(conn, actor: Actor, version_id: int) -> dict:
    v = _own_version(conn, actor, version_id)
    sections = conn.execute(
        "SELECT ordinal, heading, visibility, content FROM document_sections WHERE version_id = %s ORDER BY ordinal",
        (version_id,),
    ).fetchall()
    previous = _sections_by_heading(conn, v[4])
    items = []
    for ordinal, heading, visibility, content in sections:
        before = previous.get(_norm(heading))
        items.append({
            "ordinal": ordinal, "heading": heading, "visibility": visibility, "content": content,
            "changed": before is None or _ws(before[1]) != _ws(content),
            "previous_visibility": before[0] if before else None,
        })
    return {
        "id": v[0], "document_id": v[1], "status": v[2], "error": v[6], "file_name": v[7], "file_size": v[8],
        "page_count": v[9], "kind": v[10], "created_at": v[12].isoformat(), "title": v[13], "project_id": v[14],
        "doc_type": v[15], "is_new_version": v[4] is not None, "published": v[17] is not None,
        "draft_expires_at": v[5].isoformat() if v[5] else None,
        "sections": items, "summary": _summary(s["visibility"] for s in items),
        "client_name": _client_name(conn, v[14]),
    }


def _sections_by_heading(conn, version_id: int | None) -> dict[str, tuple[str, str]]:
    if version_id is None:
        return {}
    return {_norm(h): (v, c) for h, v, c in conn.execute(
        "SELECT heading, visibility, content FROM document_sections WHERE version_id = %s", (version_id,))}


def _client_name(conn, project_id: str | None) -> str | None:
    if project_id is None:
        return None
    row = conn.execute("SELECT client_name FROM projects WHERE id = %s", (project_id,)).fetchone()
    return row[0] if row else None


def _summary(levels) -> dict[str, int]:
    counts = {level: 0 for level in LEVELS}
    for level in levels:
        counts[level] += 1
    return counts


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def replace_sections(conn, actor: Actor, version_id: int, sections: list[dict]) -> dict:
    """Save the reviewer's edits: renames, merges, splits and levels.

    The text itself can only be re-partitioned, never changed: the concatenated content must equal
    the parsed content (whitespace-insensitive). That keeps review from adding or dropping text.
    """
    if not sections or len(sections) > MAX_SECTIONS:
        raise UploadError(422, f"A document needs 1–{MAX_SECTIONS} sections.")
    for s in sections:
        if s.get("visibility") not in RANK:
            raise UploadError(422, "Each section needs a valid visibility level.")
        if not str(s.get("heading", "")).strip() or len(s["heading"]) > 200:
            raise UploadError(422, "Each section needs a heading of at most 200 characters.")
        if not str(s.get("content", "")).strip():
            raise UploadError(422, "Sections can't be empty — merge them instead.")
    with conn.transaction():
        v = _own_version(conn, actor, version_id, lock=True)
        if v[2] != "draft":
            raise UploadError(409, "Only drafts can be edited.")
        original = "".join(_ws(c).replace(" ", "") for (c,) in conn.execute(
            "SELECT content FROM document_sections WHERE version_id = %s ORDER BY ordinal", (version_id,)))
        edited = "".join(_ws(s["content"]).replace(" ", "") for s in sections)
        if original != edited:
            raise UploadError(422, "Sections can be renamed, merged or split, but the text itself can't be changed.")
        conn.execute("DELETE FROM document_sections WHERE version_id = %s", (version_id,))
        for n, s in enumerate(sections):
            conn.execute(
                """INSERT INTO document_sections (version_id, document_id, ordinal, heading, visibility, content)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (version_id, v[1], n, s["heading"].strip(), s["visibility"], s["content"].strip()),
            )
    return get_upload(conn, actor, version_id)


def publish(conn, actor: Actor, version_id: int) -> dict:
    with conn.transaction():
        v = _own_version(conn, actor, version_id, lock=True)
        document_id, status, base = v[1], v[2], v[4]
        retry = status == "failed" and v[17] is not None          # publishing failed during embedding
        if status != "draft" and not retry:
            raise UploadError(409, "Only drafts can be published.")
        doc = conn.execute(
            "SELECT current_version_id, project_id, doc_type FROM documents WHERE id = %s FOR UPDATE",
            (document_id,),
        ).fetchone()
        if not can_upload(conn, actor, doc[1], doc[2]):                 # re-check at publish (Q8)
            raise UploadError(403, "You no longer have permission to publish to this project.")
        if doc[0] != base:
            who = conn.execute(
                """SELECT u.name FROM document_versions v LEFT JOIN users u ON u.id = coalesce(v.published_by, v.uploaded_by)
                   WHERE v.id = %s""", (doc[0],)).fetchone()
            raise UploadError(409, f"A newer version was published{' by ' + who[0] if who and who[0] else ''} "
                                   "after you started. Review the changes and upload again.")
        if conn.execute("SELECT 1 FROM document_versions WHERE document_id = %s AND status = 'processing' AND id <> %s",
                        (document_id, version_id)).fetchone():
            raise UploadError(409, "Another version of this document is being published right now.")

        previous = _levels_by_heading(conn, base)
        sections = conn.execute("SELECT ordinal, heading, visibility FROM document_sections WHERE version_id = %s",
                                (version_id,)).fetchall()
        conn.execute("UPDATE document_sections SET visibility_set_by = %s, visibility_set_at = now() "
                     "WHERE version_id = %s", (actor.id, version_id))
        for ordinal, heading, visibility in sections:
            conn.execute(
                """INSERT INTO visibility_changes (document_id, version_id, ordinal, heading, old_visibility,
                                                   new_visibility, context, changed_by)
                   VALUES (%s, %s, %s, %s, %s, %s, 'publish', %s)""",
                (document_id, version_id, ordinal, heading, previous.get(_norm(heading)), visibility, actor.id),
            )
        conn.execute(
            """UPDATE document_versions SET status = 'processing', published_by = %s, published_at = now(),
                 attempts = 0, next_attempt_at = now(), locked_until = NULL, draft_expires_at = NULL WHERE id = %s""",
            (actor.id, version_id),
        )
    return {"status": "processing", "summary": _summary(s[2] for s in sections)}


def discard(conn, storage: LocalStorage, actor: Actor, version_id: int) -> None:
    with conn.transaction():
        v = _own_version(conn, actor, version_id, lock=True)
        if v[2] not in ("draft", "failed", "parsing"):
            raise UploadError(409, "Only drafts and failed uploads can be discarded.")
        _discard(conn, version_id, v[1])
    _unlink_if_unused(conn, storage, v[11])


def _discard(conn, version_id: int, document_id: str) -> None:
    conn.execute("DELETE FROM document_sections WHERE version_id = %s", (version_id,))
    conn.execute("UPDATE document_versions SET status = 'discarded', draft_expires_at = NULL, locked_until = NULL "
                 "WHERE id = %s", (version_id,))
    # A brand-new document that never went live disappears with its last draft.
    conn.execute(
        """DELETE FROM documents d WHERE d.id = %s AND d.current_version_id IS NULL
             AND NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id = d.id
                             AND v.status IN ('parsing', 'draft', 'processing'))""",
        (document_id,),
    )


def expire_drafts(conn, storage: LocalStorage) -> int:
    expired = 0
    while True:
        with conn.transaction():
            row = conn.execute(
                """SELECT id, document_id, file_key FROM document_versions
                   WHERE status = 'draft' AND draft_expires_at < now() LIMIT 1 FOR UPDATE SKIP LOCKED"""
            ).fetchone()
            if row is None:
                return expired
            _discard(conn, row[0], row[1])
            expired += 1
        _unlink_if_unused(conn, storage, row[2])


def list_uploads(conn, actor: Actor) -> list[dict]:
    rows = conn.execute(
        """SELECT v.id, d.title, d.project_id, d.doc_type, v.status, v.error, v.file_name, v.created_at,
                  v.base_version_id IS NOT NULL
           FROM document_versions v JOIN documents d ON d.id = v.document_id
           WHERE v.drafted_by = %s AND v.status <> 'discarded'
           ORDER BY v.created_at DESC LIMIT 50""",
        (actor.id,),
    ).fetchall()
    return [{"id": r[0], "title": r[1], "project_id": r[2], "doc_type": r[3], "status": r[4], "error": r[5],
             "file_name": r[6], "created_at": r[7].isoformat(), "is_new_version": r[8]} for r in rows]


def original_file(conn, storage: LocalStorage, actor: Actor, version_id: int) -> tuple[Path, str]:
    """Originals contain every section — only the uploader and the CEO may download them."""
    v = _own_version(conn, actor, version_id)
    return storage.path(v[11]), v[7]


# ---------------------------------------------------------------------------------------------
# Live documents
# ---------------------------------------------------------------------------------------------

def manageable_documents(conn, actor: Actor) -> list[dict]:
    docs = conn.execute(
        """SELECT d.id, d.title, d.project_id, d.doc_type, d.current_version_id, d.updated_at
           FROM documents d WHERE d.company_id = %s AND d.current_version_id IS NOT NULL AND d.deleted_at IS NULL
           ORDER BY d.project_id NULLS LAST, d.title""",
        (actor.company_id,),
    ).fetchall()
    out = []
    for doc_id, title, project_id, doc_type, current, updated in docs:
        if not can_upload(conn, actor, project_id, doc_type):
            continue
        sections = conn.execute(
            "SELECT ordinal, heading, visibility FROM document_sections WHERE version_id = %s ORDER BY ordinal",
            (current,)).fetchall()
        has_previous = conn.execute(
            "SELECT 1 FROM document_versions WHERE document_id = %s AND status = 'superseded' AND id < %s LIMIT 1",
            (doc_id, current)).fetchone() is not None
        out.append({"id": doc_id, "title": title, "project_id": project_id, "doc_type": doc_type,
                    "updated_at": updated.isoformat(), "can_restore": has_previous,
                    "client_name": _client_name(conn, project_id),
                    "sections": [{"ordinal": o, "heading": h, "visibility": v} for o, h, v in sections]})
    return out


def set_live_visibility(conn, actor: Actor, document_id: str, ordinal: int, visibility: str) -> dict:
    """Fix a level on a live document: section and chunks change in one transaction (Q9)."""
    if visibility not in RANK:
        raise UploadError(422, "Invalid visibility level.")
    with conn.transaction():
        doc = _manageable_document(conn, actor, document_id, lock=True)
        row = conn.execute(
            "SELECT id, heading, visibility FROM document_sections WHERE version_id = %s AND ordinal = %s FOR UPDATE",
            (doc[3], ordinal),
        ).fetchone()
        if row is None:
            raise UploadError(404, "Section not found")
        section_id, heading, old = row
        if old != visibility:
            conn.execute("UPDATE document_sections SET visibility = %s, visibility_set_by = %s, "
                         "visibility_set_at = now() WHERE id = %s", (visibility, actor.id, section_id))
            conn.execute("UPDATE chunks SET visibility = %s WHERE section_id = %s", (visibility, section_id))
            conn.execute(
                """INSERT INTO visibility_changes (document_id, version_id, ordinal, heading, old_visibility,
                                                   new_visibility, context, changed_by)
                   VALUES (%s, %s, %s, %s, %s, %s, 'live_edit', %s)""",
                (document_id, doc[3], ordinal, heading, old, visibility, actor.id),
            )
    return {"ordinal": ordinal, "heading": heading, "visibility": visibility, "previous": old}


def restore_previous(conn, actor: Actor, document_id: str) -> dict:
    """Make the previous version live again — its chunks are still stored, so this is instant."""
    with conn.transaction():
        doc = _manageable_document(conn, actor, document_id, lock=True)
        current, deleted_at = doc[3], doc[6]
        if conn.execute("SELECT 1 FROM document_versions WHERE document_id = %s AND status = 'processing'",
                        (document_id,)).fetchone():
            raise UploadError(409, "A version of this document is being published right now.")
        prev = conn.execute(
            """SELECT v.id FROM document_versions v WHERE v.document_id = %s AND v.status = 'superseded'
                 AND v.id < %s AND EXISTS (SELECT 1 FROM chunks c WHERE c.version_id = v.id)
               ORDER BY v.id DESC LIMIT 1""",
            (document_id, current),
        ).fetchone()
        if prev is None:
            raise UploadError(409, "There is no previous version to restore.")
        prev = prev[0]
        live = "deleted" if deleted_at is not None else "ready"
        conn.execute("UPDATE chunks SET status = 'superseded' WHERE version_id = %s", (current,))
        conn.execute("UPDATE chunks SET status = %s WHERE version_id = %s", (live, prev))
        conn.execute("UPDATE document_versions SET status = 'superseded' WHERE id = %s", (current,))
        conn.execute("UPDATE document_versions SET status = 'ready' WHERE id = %s", (prev,))
        conn.execute("UPDATE documents SET current_version_id = %s, updated_at = now() WHERE id = %s",
                     (prev, document_id))
        for ordinal, heading, visibility in conn.execute(
                "SELECT ordinal, heading, visibility FROM document_sections WHERE version_id = %s", (prev,)).fetchall():
            conn.execute(
                """INSERT INTO visibility_changes (document_id, version_id, ordinal, heading, old_visibility,
                                                   new_visibility, context, changed_by)
                   VALUES (%s, %s, %s, %s, NULL, %s, 'restore', %s)""",
                (document_id, prev, ordinal, heading, visibility, actor.id),
            )
    return {"document_id": document_id, "current_version_id": prev}
