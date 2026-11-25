"""Project teams: who may add, remove and re-role whom (design review 2026-11-25, Q6)."""

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from app import auth
from app.api import app
from app.embeddings import HashingEmbedder
from app.llm import ExtractiveLLM
from app.retrieval import retrieve

from .db_helpers import TEST_DSN

EMAILS = {"mona": "mona@xyz.test", "hamed": "hamed@xyz.test", "sara": "sara@xyz.test",
          "youssef": "youssef@xyz.test", "omar": "omar@xyz.test"}


@pytest.fixture(scope="module")
def client(db):
    app.state.pool = ConnectionPool(TEST_DSN, kwargs={"autocommit": True}, min_size=1, max_size=4, open=True)
    app.state.embedder, app.state.llm = HashingEmbedder(), ExtractiveLLM()
    with TestClient(app) as c:
        yield c
    del app.state.pool


@pytest.fixture(scope="module")
def h(client):
    out = {}
    for name, email in EMAILS.items():
        r = client.post("/api/auth/login", json={"email": email, "password": auth.demo_password()})
        out[name] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


@pytest.fixture(autouse=True)
def restore_team(db, client):
    yield
    db.execute("DELETE FROM project_members")
    db.execute("""INSERT INTO project_members VALUES ('u-hamed','P001'), ('u-sara','P001'), ('u-omar','P001'),
                  ('u-khaled','P001'), ('u-amina','P001'), ('u-youssef','P002')""")
    db.execute("UPDATE users SET role = 'developer' WHERE id = 'u-sara'")
    db.execute("UPDATE users SET role = 'pm' WHERE id = 'u-hamed'")
    db.execute("DELETE FROM projects WHERE id NOT IN ('P001', 'P002')")


def members(client, headers, pid):
    team = client.get("/api/team", headers=headers).json()
    return {m["id"] for p in team["projects"] if p["id"] == pid for m in p["members"]}


def test_overview_scope(client, h):
    assert {p["id"] for p in client.get("/api/team", headers=h["mona"]).json()["projects"]} == {"P001", "P002"}
    pm = client.get("/api/team", headers=h["hamed"]).json()
    assert [p["id"] for p in pm["projects"]] == ["P001"] and not pm["can_change_roles"]
    assert client.get("/api/team", headers=h["sara"]).status_code == 403


def test_pm_adds_and_removes_on_own_project(client, db, h):
    r = client.post("/api/team/projects/P001/members", headers=h["hamed"], json={"user_id": "u-youssef"})
    assert r.status_code == 200 and "u-youssef" in members(client, h["hamed"], "P001")
    # Takes effect on the next question: Youssef now reads Droob documents.
    assert any(c.document_id.startswith("droob") for c in
               retrieve(db, "u-youssef", "requirements", HashingEmbedder(), k=50, audit=False).chunks)
    assert client.delete("/api/team/projects/P001/members/u-youssef", headers=h["hamed"]).status_code == 200
    assert "u-youssef" not in members(client, h["hamed"], "P001")
    assert [r[0] for r in db.execute("SELECT action FROM membership_changes WHERE user_id = 'u-youssef' "
                                     "AND project_id = 'P001' ORDER BY id")][-2:] == ["add", "remove"]


def test_pm_cannot_touch_other_projects_or_pms(client, h):
    assert client.post("/api/team/projects/P002/members", headers=h["hamed"],
                       json={"user_id": "u-sara"}).status_code == 404
    assert client.delete("/api/team/projects/P001/members/u-hamed", headers=h["hamed"]).status_code == 403
    assert client.post("/api/team/projects", headers=h["hamed"], json={"name": "X"}).status_code == 403
    assert client.patch("/api/team/users/u-sara/role", headers=h["hamed"], json={"role": "qa"}).status_code == 403


def test_non_managers_cannot_change_teams(client, h):
    assert client.post("/api/team/projects/P001/members", headers=h["sara"],
                       json={"user_id": "u-youssef"}).status_code == 404


def test_ceo_creates_project_and_assigns_pm(client, h):
    r = client.post("/api/team/projects", headers=h["mona"], json={"name": "Nile Shop", "client": "NRG"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert pid == "P003"
    assert client.post(f"/api/team/projects/{pid}/members", headers=h["mona"],
                       json={"user_id": "u-hamed"}).status_code == 200
    assert pid in [p["id"] for p in client.get("/api/team", headers=h["hamed"]).json()["projects"]]


def test_last_pm_cannot_be_removed(client, h):
    r = client.delete("/api/team/projects/P001/members/u-hamed", headers=h["mona"])
    assert r.status_code == 409 and "needs a project manager" in r.json()["detail"]


def test_role_changes(client, db, h):
    r = client.patch("/api/team/users/u-sara/role", headers=h["mona"], json={"role": "qa"})
    assert r.status_code == 200 and r.json()["previous"] == "developer"
    assert client.get("/api/me", headers=h["sara"]).json()["role"] == "qa"            # next request
    assert client.patch("/api/team/users/u-hamed/role", headers=h["mona"], json={"role": "developer"}).status_code == 409
    assert client.patch("/api/team/users/u-mona/role", headers=h["mona"], json={"role": "pm"}).status_code == 422
    assert client.patch("/api/team/users/u-sara/role", headers=h["mona"], json={"role": "ceo"}).status_code == 422
