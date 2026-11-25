"""FastAPI application.

    cd backend && ../.venv/bin/uvicorn app.api:app --reload --port 8000

All routes except login, health and the demo-user list need a Bearer token. The authenticated user
is re-loaded from the database on every request; an inactive or deleted user gets 401.
"""

from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime

import jwt
import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from .answer import HISTORY_MESSAGES, answer_question
from .auth import (
    TOKEN_TTL_SECONDS,
    LoginRateLimiter,
    create_token,
    decode_token,
    demo_mode,
    demo_password,
    verify_password,
)
from .db import default_dsn
from .embeddings import default_embedder
from .llm import default_llm
from .retrieval import accessible_projects, fetch_chunk_for_user, load_scope
from . import team, uploads
from .storage import LocalStorage
from .topics import ROLE_LABEL, rules_from_db
from .uploads import UploadError
from .worker import start_in_background, worker_in_process


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "pool"):
        app.state.pool = ConnectionPool(default_dsn(), kwargs={"autocommit": True}, min_size=1, max_size=10, open=True)
    app.state.embedder = getattr(app.state, "embedder", None) or default_embedder()
    app.state.llm = getattr(app.state, "llm", None) or default_llm()
    app.state.login_limiter = LoginRateLimiter()
    app.state.storage = getattr(app.state, "storage", None) or LocalStorage()
    stop = None
    if getattr(app.state, "start_worker", worker_in_process()):
        stop = start_in_background(app.state.embedder, app.state.storage)
    yield
    if stop:
        stop.set()
    app.state.pool.close()


app = FastAPI(title="XYZ PM Assistant", lifespan=lifespan)
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------------------------

def get_conn(request: Request):
    with request.app.state.pool.connection() as conn:
        yield conn


@dataclass(frozen=True)
class CurrentUser:
    id: str
    name: str
    email: str
    role: str
    company_id: str
    organization: str | None


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 conn: psycopg.Connection = Depends(get_conn)) -> CurrentUser:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        user_id = decode_token(creds.credentials)
    except jwt.InvalidTokenError:
        raise unauthorized
    row = conn.execute(
        "SELECT id, name, email, role, company_id, organization FROM users WHERE id = %s AND is_active",
        (user_id,),
    ).fetchone()
    if row is None:
        raise unauthorized
    return CurrentUser(*row)


# ---------------------------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/auth/demo-users")
def demo_users(conn: psycopg.Connection = Depends(get_conn)):
    """Powers the login page's user switcher. Disabled unless DEMO_MODE is on."""
    if not demo_mode():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    rows = conn.execute(
        """SELECT u.id, u.name, u.email, u.role, u.organization,
                  coalesce(array_agg(p.name ORDER BY p.id) FILTER (WHERE p.id IS NOT NULL), '{}')
           FROM users u
           LEFT JOIN project_members m ON m.user_id = u.id
           LEFT JOIN projects p ON p.id = m.project_id
           WHERE u.is_active
           GROUP BY u.id ORDER BY u.name"""
    ).fetchall()
    return {
        "password": demo_password(),
        "users": [
            {"id": r[0], "name": r[1], "email": r[2], "role": r[3], "organization": r[4], "projects": r[5]}
            for r in rows
        ],
    }


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request, conn: psycopg.Connection = Depends(get_conn)):
    limiter: LoginRateLimiter = request.app.state.login_limiter
    key = body.email.strip().lower()
    if limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again later.")
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE lower(email) = %s AND is_active", (key,)
    ).fetchone()
    if not verify_password(body.password, row[1] if row else None):
        limiter.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    limiter.reset(key)
    return {"access_token": create_token(row[0]), "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}


@app.get("/api/me")
def me(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    scope = load_scope(conn, user.id)
    project_ids = sorted(accessible_projects(conn, scope))
    projects = conn.execute(
        "SELECT id, name FROM projects WHERE id = ANY(%s) ORDER BY id", (project_ids,)
    ).fetchall()
    labels = rules_from_db(conn).topics
    return {
        **asdict(user),
        "role_label": ROLE_LABEL.get(user.role, user.role),
        "projects": [{"id": p[0], "name": p[1]} for p in projects],
        "company_wide": scope.company_wide,
        # What this role may read, per document type (topic labels) — shown in the UI.
        "access": {dt: [labels[dt][t] for t in scope.topics_for(dt) if t in labels.get(dt, {})] for dt in labels},
        "can_upload": user.role in {"ceo", "pm"},
    }


# ---------------------------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------------------------

class NewConversation(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _encode_cursor(ts: datetime, row_id: int) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        ts, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), int(row_id)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor")


def _own_conversation(conn, user: CurrentUser, conversation_id: int):
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _conversation_json(row) -> dict:
    return {"id": row[0], "title": row[1], "created_at": row[2].isoformat(), "updated_at": row[3].isoformat()}


# Internal outcomes say WHY there was no answer (e.g. "out_of_scope_project" confirms that a named
# project exists). Users only ever see whether they got an answer; the reason stays in audit_log.
_PUBLIC_OUTCOME = {"answered": "answered", "chat": "answered", "llm_error": "error"}


def _message_json(row) -> dict:
    outcome = None if row[3] is None else _PUBLIC_OUTCOME.get(row[3], "no_answer")
    return {"id": row[0], "role": row[1], "content": row[2], "outcome": outcome,
            "citations": row[4], "created_at": row[5].isoformat()}


@app.get("/api/conversations")
def list_conversations(limit: int = Query(20, ge=1, le=100), cursor: str | None = None,
                       user: CurrentUser = Depends(current_user),
                       conn: psycopg.Connection = Depends(get_conn)):
    params: dict = {"user": user.id, "limit": limit + 1}
    where = "user_id = %(user)s"
    if cursor:
        params["ts"], params["id"] = _decode_cursor(cursor)
        where += " AND (updated_at, id) < (%(ts)s, %(id)s)"
    rows = conn.execute(
        f"""SELECT id, title, created_at, updated_at FROM conversations WHERE {where}
            ORDER BY updated_at DESC, id DESC LIMIT %(limit)s""", params,
    ).fetchall()
    page, more = rows[:limit], len(rows) > limit
    return {"items": [_conversation_json(r) for r in page],
            "next_cursor": _encode_cursor(page[-1][3], page[-1][0]) if more else None}


@app.post("/api/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(body: NewConversation, user: CurrentUser = Depends(current_user),
                        conn: psycopg.Connection = Depends(get_conn)):
    row = conn.execute(
        """INSERT INTO conversations (company_id, user_id, title) VALUES (%s, %s, %s)
           RETURNING id, title, created_at, updated_at""",
        (user.company_id, user.id, body.title or "New conversation"),
    ).fetchone()
    return _conversation_json(row)


@app.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: CurrentUser = Depends(current_user),
                        conn: psycopg.Connection = Depends(get_conn)):
    _own_conversation(conn, user, conversation_id)
    conn.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user.id))


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, limit: int = Query(50, ge=1, le=200), before: str | None = None,
                  user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Newest page first; items within a page are oldest → newest. Pass next_before for older messages."""
    _own_conversation(conn, user, conversation_id)
    params: dict = {"cid": conversation_id, "limit": limit + 1}
    where = "conversation_id = %(cid)s"
    if before:
        params["ts"], params["id"] = _decode_cursor(before)
        where += " AND (created_at, id) < (%(ts)s, %(id)s)"
    rows = conn.execute(
        f"""SELECT id, role, content, outcome, citations, created_at FROM messages WHERE {where}
            ORDER BY created_at DESC, id DESC LIMIT %(limit)s""", params,
    ).fetchall()
    page, more = rows[:limit], len(rows) > limit
    return {"items": [_message_json(r) for r in reversed(page)],
            "next_before": _encode_cursor(page[-1][5], page[-1][0]) if more else None}


@app.post("/api/conversations/{conversation_id}/messages")
def ask(conversation_id: int, body: Question, request: Request,
        user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Answer a chat message. Every message re-retrieves with the user's CURRENT permissions. The
    recent turns of THIS conversation go to the model for context — they are the user's own messages,
    already on their screen, so they reveal nothing new."""
    conv = _own_conversation(conn, user, conversation_id)
    question = body.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Question is empty")
    recent = conn.execute(
        """SELECT role, content FROM messages WHERE conversation_id = %s
           ORDER BY created_at DESC, id DESC LIMIT %s""",
        (conversation_id, HISTORY_MESSAGES),
    ).fetchall()
    answer = answer_question(conn, user.id, question, history=[(r, c) for r, c in reversed(recent)],
                             embedder=request.app.state.embedder, llm=request.app.state.llm)
    citations = [
        {"number": c.number, "chunk_id": c.chunk_id, "document_id": c.document_id,
         "document_title": c.document_title, "heading": c.heading, "snippet": c.snippet}
        for c in answer.citations
    ]
    with conn.transaction():
        user_row = conn.execute(
            """INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)
               RETURNING id, role, content, outcome, citations, created_at""",
            (conversation_id, question),
        ).fetchone()
        assistant_row = conn.execute(
            """INSERT INTO messages (conversation_id, role, content, outcome, citations)
               VALUES (%s, 'assistant', %s, %s, %s::jsonb)
               RETURNING id, role, content, outcome, citations, created_at""",
            (conversation_id, answer.text, answer.outcome, json.dumps(citations)),
        ).fetchone()
        title = conv[1] if conv[1] != "New conversation" else question[:60] + ("…" if len(question) > 60 else "")
        conn.execute("UPDATE conversations SET updated_at = now(), title = %s WHERE id = %s",
                     (title, conversation_id))
    return {"user_message": _message_json(user_row), "assistant_message": _message_json(assistant_row),
            "conversation_title": title}


# ---------------------------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------------------------

@app.get("/api/citations/{chunk_id}")
def open_citation(chunk_id: int, user: CurrentUser = Depends(current_user),
                  conn: psycopg.Connection = Depends(get_conn)):
    """Re-checks access at open time. Missing and no-longer-permitted look the same (404)."""
    chunk = fetch_chunk_for_user(conn, user.id, chunk_id)
    if chunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This source is not available to you")
    return {"chunk_id": chunk.id, "document_id": chunk.document_id, "document_title": chunk.document_title,
            "project_id": chunk.project_id, "heading": chunk.heading,
            "content": chunk.content.split("\n\n", 1)[-1]}


# ---------------------------------------------------------------------------------------------
# Uploads (CEO and PM) — see uploads.py for the rules
# ---------------------------------------------------------------------------------------------

def _actor(user: CurrentUser) -> uploads.Actor:
    return uploads.Actor(user.id, user.role, user.company_id)


def _upload_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except UploadError as exc:
        raise HTTPException(exc.status, exc.message)


class SectionEdit(BaseModel):
    heading: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    topic: str


class SectionsBody(BaseModel):
    sections: list[SectionEdit] = Field(min_length=1, max_length=uploads.MAX_SECTIONS)
    lock_version: int


class TopicBody(BaseModel):
    topic: str


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    client: str | None = Field(default=None, max_length=120)


class MemberBody(BaseModel):
    user_id: str


class RoleBody(BaseModel):
    role: str


@app.get("/api/uploads/options")
def upload_options(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    return uploads.upload_options(conn, _actor(user))


@app.post("/api/uploads", status_code=status.HTTP_202_ACCEPTED)
def create_upload(request: Request, file: UploadFile = File(...), doc_type: str | None = Form(None),
                  project_id: str | None = Form(None), title: str | None = Form(None),
                  document_id: str | None = Form(None),
                  user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > uploads.MAX_UPLOAD_BYTES + 64 * 1024:
        raise HTTPException(413, "Files can be at most 20 MB.")
    version_id = _upload_call(
        uploads.create_upload, conn, request.app.state.storage, _actor(user), file.file, file.filename or "upload",
        doc_type=doc_type, project_id=project_id or None, title=title, document_id=document_id or None,
    )
    return {"id": version_id, "status": "parsing"}


@app.get("/api/uploads/review-requests")
def review_requests(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Drafts in my projects that still have unclassified sections (CEO: every project)."""
    return {"items": uploads.review_requests(conn, _actor(user))}


@app.get("/api/uploads")
def list_uploads(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    return {"items": uploads.list_uploads(conn, _actor(user))}


@app.get("/api/uploads/{version_id}")
def get_upload(version_id: int, user: CurrentUser = Depends(current_user),
               conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(uploads.get_upload, conn, _actor(user), version_id)


@app.put("/api/uploads/{version_id}/sections")
def save_sections(version_id: int, body: SectionsBody, user: CurrentUser = Depends(current_user),
                  conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(uploads.replace_sections, conn, _actor(user), version_id,
                        [s.model_dump() for s in body.sections], body.lock_version)


@app.post("/api/uploads/{version_id}/publish")
def publish_upload(version_id: int, user: CurrentUser = Depends(current_user),
                   conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(uploads.publish, conn, _actor(user), version_id)


@app.post("/api/uploads/{version_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
def discard_upload(version_id: int, request: Request, user: CurrentUser = Depends(current_user),
                   conn: psycopg.Connection = Depends(get_conn)):
    _upload_call(uploads.discard, conn, request.app.state.storage, _actor(user), version_id)


@app.get("/api/uploads/{version_id}/file")
def download_original(version_id: int, request: Request, user: CurrentUser = Depends(current_user),
                      conn: psycopg.Connection = Depends(get_conn)):
    """Only the uploader and the CEO: the original contains every section."""
    path, name = _upload_call(uploads.original_file, conn, request.app.state.storage, _actor(user), version_id)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/api/documents/manage")
def manageable_documents(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    return {"items": uploads.manageable_documents(conn, _actor(user))}


@app.patch("/api/documents/{document_id}/sections/{ordinal}")
def change_topic(document_id: str, ordinal: int, body: TopicBody,
                 user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(uploads.set_live_topic, conn, _actor(user), document_id, ordinal, body.topic)


@app.post("/api/documents/{document_id}/restore-previous")
def restore_previous(document_id: str, user: CurrentUser = Depends(current_user),
                     conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(uploads.restore_previous, conn, _actor(user), document_id)


# ---------------------------------------------------------------------------------------------
# Teams (CEO and PM) — see team.py for the rules
# ---------------------------------------------------------------------------------------------

@app.get("/api/team")
def get_team(user: CurrentUser = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(team.team_overview, conn, _actor(user))


@app.post("/api/team/projects", status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectBody, user: CurrentUser = Depends(current_user),
                   conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(team.create_project, conn, _actor(user), body.name, body.client)


@app.post("/api/team/projects/{project_id}/members")
def add_member(project_id: str, body: MemberBody, user: CurrentUser = Depends(current_user),
               conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(team.add_member, conn, _actor(user), project_id, body.user_id)


@app.delete("/api/team/projects/{project_id}/members/{member_id}")
def remove_member(project_id: str, member_id: str, user: CurrentUser = Depends(current_user),
                  conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(team.remove_member, conn, _actor(user), project_id, member_id)


@app.patch("/api/team/users/{user_id}/role")
def change_role(user_id: str, body: RoleBody, user: CurrentUser = Depends(current_user),
                conn: psycopg.Connection = Depends(get_conn)):
    return _upload_call(team.change_role, conn, _actor(user), user_id, body.role)
