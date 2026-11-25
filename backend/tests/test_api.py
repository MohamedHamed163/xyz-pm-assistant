"""HTTP API: authentication, conversation isolation, pagination, citations, permission changes."""

import time

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from app.api import app
from app.auth import create_token, demo_password
from app.embeddings import HashingEmbedder
from app.llm import ExtractiveLLM

from .db_helpers import TEST_DSN

NEUTRAL = "I couldn't find information about that in the documents available to you."


@pytest.fixture(scope="module")
def client(db):
    app.state.pool = ConnectionPool(TEST_DSN, kwargs={"autocommit": True}, min_size=1, max_size=4, open=True)
    app.state.embedder = HashingEmbedder()
    app.state.llm = ExtractiveLLM()
    with TestClient(app) as c:
        yield c
    del app.state.pool


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": demo_password()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def sara(client):
    return login(client, "sara@xyz.test")


@pytest.fixture(scope="module")
def amina(client):
    return login(client, "amina@droob.test")


def new_conversation(client, headers):
    r = client.post("/api/conversations", json={}, headers=headers)
    assert r.status_code == 201
    return r.json()["id"]


def ask(client, headers, cid, question):
    r = client.post(f"/api/conversations/{cid}/messages", json={"question": question}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["assistant_message"]


# --- Authentication -----------------------------------------------------------------------------

def test_login_wrong_password_and_unknown_email_look_the_same(client):
    a = client.post("/api/auth/login", json={"email": "sara@xyz.test", "password": "nope"})
    b = client.post("/api/auth/login", json={"email": "ghost@xyz.test", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_login_is_case_insensitive_on_email(client):
    login(client, "SARA@XYZ.TEST")


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "brute@xyz.test", "password": "x"})
    r = client.post("/api/auth/login", json={"email": "brute@xyz.test", "password": "x"})
    assert r.status_code == 429


@pytest.mark.parametrize("header", [None, "Bearer not-a-jwt", "Bearer " + create_token("u-sara")[:-4] + "AAAA"])
def test_missing_or_tampered_token_is_rejected(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.get("/api/me", headers=headers).status_code == 401


def test_expired_token_is_rejected(client):
    old = create_token("u-sara", now=time.time() - 7200)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_deactivated_user_is_locked_out_immediately(client, db):
    headers = login(client, "omar@xyz.test")
    assert client.get("/api/me", headers=headers).status_code == 200
    db.execute("UPDATE users SET is_active = false WHERE id = 'u-omar'")
    try:
        assert client.get("/api/me", headers=headers).status_code == 401
    finally:
        db.execute("UPDATE users SET is_active = true WHERE id = 'u-omar'")


def test_demo_users_list(client):
    body = client.get("/api/auth/demo-users").json()
    assert {u["name"] for u in body["users"]} == {"Hamed", "Sara", "Omar", "Youssef", "Mona", "Amina", "Khaled"}


def test_me_reflects_role_and_projects(client, sara, amina):
    s = client.get("/api/me", headers=sara).json()
    a = client.get("/api/me", headers=amina).json()
    assert (s["role"], s["role_label"], [p["id"] for p in s["projects"]]) == ("developer", "Developer", ["P001"])
    assert (a["role"], [p["id"] for p in a["projects"]]) == ("client", ["P001"])
    assert "Business rules" not in s["access"]["brd"] and "Requirements & scope" in s["access"]["brd"]
    mona = client.get("/api/me", headers=login(client, "mona@xyz.test")).json()
    assert mona["company_wide"] and len(mona["projects"]) == 2


# --- Conversations ------------------------------------------------------------------------------

def test_ask_stores_both_messages_with_citations(client, sara):
    cid = new_conversation(client, sara)
    answer = ask(client, sara, cid, "What are the business requirements?")
    assert answer["outcome"] == "answered"
    assert answer["citations"][0]["document_id"] == "droob-brd"
    msgs = client.get(f"/api/conversations/{cid}/messages", headers=sara).json()["items"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["citations"] == answer["citations"]
    title = client.get("/api/conversations", headers=sara).json()["items"][0]["title"]
    assert title.startswith("What are the business requirements")


def test_refusal_is_stored_as_neutral(client, sara):
    cid = new_conversation(client, sara)
    answer = ask(client, sara, cid, "What is the Hub Drives scope?")
    assert (answer["content"], answer["outcome"], answer["citations"]) == (NEUTRAL, "no_answer", [])


def test_api_never_reveals_why_there_was_no_answer(client, amina, db):
    """'out_of_scope_project' would confirm that Hub Drives is a project. Users see only 'no_answer'."""
    cid = new_conversation(client, amina)
    out_of_scope = ask(client, amina, cid, "What is the Hub Drives budget?")
    not_found = ask(client, amina, cid, "zebra quantum xylophone")
    assert out_of_scope == {**out_of_scope, "outcome": "no_answer", "content": NEUTRAL}
    assert not_found == {**not_found, "outcome": "no_answer", "content": NEUTRAL}
    internal = db.execute(
        "SELECT outcome FROM audit_log WHERE user_id = 'u-amina' ORDER BY id DESC LIMIT 2").fetchall()
    assert {r[0] for r in internal} == {"out_of_scope_project", "not_in_context"}


def test_other_users_conversation_is_invisible(client, sara, amina):
    cid = new_conversation(client, sara)
    ask(client, sara, cid, "What are the business requirements?")
    assert client.get(f"/api/conversations/{cid}/messages", headers=amina).status_code == 404
    r = client.post(f"/api/conversations/{cid}/messages", json={"question": "hi"}, headers=amina)
    assert r.status_code == 404
    assert client.delete(f"/api/conversations/{cid}", headers=amina).status_code == 404
    assert cid not in [c["id"] for c in client.get("/api/conversations", headers=amina).json()["items"]]
    # Missing and foreign look the same.
    assert client.get("/api/conversations/999999/messages", headers=amina).json() == \
        client.get(f"/api/conversations/{cid}/messages", headers=amina).json()


def test_delete_own_conversation(client, sara):
    cid = new_conversation(client, sara)
    assert client.delete(f"/api/conversations/{cid}", headers=sara).status_code == 204
    assert client.get(f"/api/conversations/{cid}/messages", headers=sara).status_code == 404


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_questions_are_rejected(client, sara, question):
    cid = new_conversation(client, sara)
    r = client.post(f"/api/conversations/{cid}/messages", json={"question": question}, headers=sara)
    assert r.status_code == 422


# --- Pagination ---------------------------------------------------------------------------------

def test_conversation_list_keyset_pagination(client):
    headers = login(client, "youssef@xyz.test")
    created = {new_conversation(client, headers) for _ in range(5)}
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = client.get("/api/conversations", params=params, headers=headers).json()
        seen += [c["id"] for c in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert pages == 3 and len(seen) == len(set(seen)) and created <= set(seen)


def test_message_keyset_pagination(client, db, sara):
    cid = new_conversation(client, sara)
    for i in range(7):
        db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)", (cid, f"m{i}"))
    first = client.get(f"/api/conversations/{cid}/messages", params={"limit": 3}, headers=sara).json()
    assert [m["content"] for m in first["items"]] == ["m4", "m5", "m6"]
    second = client.get(f"/api/conversations/{cid}/messages",
                        params={"limit": 3, "before": first["next_before"]}, headers=sara).json()
    assert [m["content"] for m in second["items"]] == ["m1", "m2", "m3"]


def test_invalid_cursor_is_400(client, sara):
    assert client.get("/api/conversations", params={"cursor": "garbage!"}, headers=sara).status_code == 400


# --- Citations and permission changes -----------------------------------------------------------

def test_open_citation_rechecks_access(client, sara, amina):
    cid = new_conversation(client, sara)
    chunk_id = ask(client, sara, cid, "What are the business requirements?")["citations"][0]["chunk_id"]
    r = client.get(f"/api/citations/{chunk_id}", headers=sara)
    assert r.status_code == 200 and "BR-01" in r.json()["content"]
    youssef = login(client, "youssef@xyz.test")                     # other project
    omar = login(client, "omar@xyz.test")                           # QA: BRD requirements aren't theirs
    assert client.get(f"/api/citations/{chunk_id}", headers=omar).status_code == 404
    denied = client.get(f"/api/citations/{chunk_id}", headers=youssef)
    missing = client.get("/api/citations/99999999", headers=youssef)
    assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()


def test_moved_user_keeps_history_but_gets_nothing_new(client, db):
    """Design decision 9: history stays; new questions and citation opens use current permissions."""
    headers = login(client, "hamed@xyz.test")
    cid = new_conversation(client, headers)
    before = ask(client, headers, cid, "What are the Droob business rules?")
    assert before["outcome"] == "answered"
    db.execute("UPDATE project_members SET project_id = 'P002' WHERE user_id = 'u-hamed'")
    try:
        after = ask(client, headers, cid, "What are the Droob business rules?")
        assert (after["content"], after["outcome"]) == (NEUTRAL, "no_answer")
        history = client.get(f"/api/conversations/{cid}/messages", headers=headers).json()["items"]
        assert history[1]["outcome"] == "answered"                     # old answer still visible
        old_chunk = before["citations"][0]["chunk_id"]
        assert client.get(f"/api/citations/{old_chunk}", headers=headers).status_code == 404
    finally:
        db.execute("UPDATE project_members SET project_id = 'P001' WHERE user_id = 'u-hamed'")
