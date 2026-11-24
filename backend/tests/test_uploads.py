"""Upload feature end to end through the HTTP API (design Q3–Q9)."""

import io

import pytest
from docx import Document
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from app import auth
from app.api import app
from app.embeddings import HashingEmbedder
from app.ingestion import process_next
from app.llm import ExtractiveLLM
from app.retrieval import retrieve
from app.uploads import expire_drafts, parse_next

from .db_helpers import TEST_DSN, FailingEmbedder

EMB = HashingEmbedder()
SEED_IDS = None
EMAILS = {"hamed": "hamed@xyz.test", "sara": "sara@xyz.test", "mona": "mona@xyz.test",
          "amina": "amina@nileretail.test", "khaled": "khaled@xyz.test", "omar": "omar@xyz.test"}


@pytest.fixture(scope="module")
def client(db):
    global SEED_IDS
    SEED_IDS = [r[0] for r in db.execute("SELECT id FROM documents")]
    app.state.pool = ConnectionPool(TEST_DSN, kwargs={"autocommit": True}, min_size=1, max_size=4, open=True)
    app.state.embedder, app.state.llm = EMB, ExtractiveLLM()
    with TestClient(app) as c:
        yield c
    del app.state.pool


@pytest.fixture(autouse=True)
def cleanup(db, client):
    yield
    db.execute("DELETE FROM documents WHERE NOT (id = ANY(%s))", (SEED_IDS,))
    db.execute("INSERT INTO project_members VALUES ('u-hamed', 'P001') ON CONFLICT DO NOTHING")


@pytest.fixture(scope="module")
def h(client):
    out = {}
    for name, email in EMAILS.items():
        r = client.post("/api/auth/login", json={"email": email, "password": auth.demo_password()})
        out[name] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


def make_docx(sections: dict[str, str], title="Sprint 8 Review") -> bytes:
    d = Document()
    d.add_paragraph(title, style="Title")
    d.add_paragraph("Contents")
    for n, heading in enumerate(sections, start=1):
        d.add_paragraph(f"{heading} .......... {n + 1}")
    for heading, body in sections.items():
        d.add_paragraph(heading, style="Heading 2")
        d.add_paragraph(body)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


SPRINT8 = {
    "1. Decisions": "SPRINT8-DECISIONS card payments go live on staging on 2026-12-05.",
    "2. Demo Feedback": "SPRINT8-FEEDBACK the client liked the new checkout.",
    "3. Risks and Budget": "SPRINT8-RISKS-MGMT Paymob sandbox flaky; budget overrun of 12 percent.",
}


def upload(client, headers, data: bytes, name="Sprint 8 Review.docx", **form):
    form = {"doc_type": "minutes", "project_id": "P001", "title": "Sprint 8 Review"} | form
    return client.post("/api/uploads", headers=headers, files={"file": (name, data)}, data=form)


def parsed_draft(client, db, headers, data=None, **form):
    r = upload(client, headers, data or make_docx(SPRINT8), **form)
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    assert parse_next(db, app.state.storage) == (vid, "draft")
    return vid, client.get(f"/api/uploads/{vid}", headers=headers).json()


def set_levels(client, headers, vid, draft, levels: dict[str, str], renames: dict[str, str] | None = None):
    sections = [{"heading": (renames or {}).get(s["heading"], s["heading"]), "content": s["content"],
                 "visibility": levels.get(s["heading"], s["visibility"])} for s in draft["sections"]]
    return client.put(f"/api/uploads/{vid}/sections", headers=headers, json={"sections": sections})


def publish_and_process(client, db, headers, vid, embedder=EMB):
    r = client.post(f"/api/uploads/{vid}/publish", headers=headers)
    assert r.status_code == 200, r.text
    result = process_next(db, embedder)
    return r.json(), result


def visible(db, user_id) -> str:
    return "\n".join(c.content for c in retrieve(db, user_id, "sprint", EMB, k=10_000, audit=False).chunks)


# --- Who may upload -----------------------------------------------------------------------------

@pytest.mark.parametrize("who,form,expected", [
    ("hamed", {}, 202),                                                       # PM, own project, standard type
    ("hamed", {"doc_type": "contract"}, 403),                                 # PM, restricted type
    ("hamed", {"project_id": "P002"}, 403),                                   # PM, other project
    ("hamed", {"project_id": ""}, 403),                                       # PM, company-wide
    ("mona", {"doc_type": "contract"}, 202),                                  # CEO, restricted type
    ("mona", {"project_id": "", "doc_type": "executive_report"}, 202),        # CEO, company-wide
    ("sara", {}, 403), ("omar", {}, 403), ("amina", {}, 403), ("khaled", {}, 403),
    ("mona", {"project_id": "P999"}, 403),                                    # unknown project
])
def test_upload_permissions(client, h, who, form, expected):
    assert upload(client, h[who], make_docx(SPRINT8), **form).status_code == expected


def test_options_reflect_permissions(client, h):
    pm = client.get("/api/uploads/options", headers=h["hamed"]).json()
    assert [p["id"] for p in pm["projects"]] == ["P001"] and not pm["company_wide"]
    assert {t["name"] for t in pm["doc_types"]} == {"brd", "prd", "technical", "qa", "minutes"}
    ceo = client.get("/api/uploads/options", headers=h["mona"]).json()
    assert len(ceo["projects"]) == 3 and ceo["company_wide"] and len(ceo["doc_types"]) == 7
    assert client.get("/api/me", headers=h["sara"]).json()["can_upload"] is False


def test_file_type_and_size_are_checked(client, h):
    fake = upload(client, h["hamed"], b"MZ\x90\x00 not a document", name="report.pdf")
    assert fake.status_code == 400 and "Only PDF and Word" in fake.json()["detail"]
    big = upload(client, h["hamed"], b"%PDF-" + b"0" * (21 * 1024 * 1024))
    assert big.status_code == 413


# --- Draft → publish → live ---------------------------------------------------------------------

def test_full_flow_with_three_levels(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    assert [s["heading"] for s in draft["sections"]] == list(SPRINT8)        # TOC stripped, no Introduction
    assert {s["visibility"] for s in draft["sections"]} == {"team"}          # every section starts as Team
    assert draft["client_name"] == "Nile Retail Group"

    # A draft is invisible to everyone's search — even the CEO's — and to other users' API calls.
    for user in ("u-mona", "u-hamed", "u-sara"):
        assert "SPRINT8" not in visible(db, user)
    assert client.get(f"/api/uploads/{vid}", headers=h["sara"]).status_code == 404
    assert client.get(f"/api/uploads/{vid}", headers=h["mona"]).status_code == 200   # CEO may review

    r = set_levels(client, h["hamed"], vid, draft, {"1. Decisions": "client_shared",
                                                    "2. Demo Feedback": "client_shared",
                                                    "3. Risks and Budget": "management"})
    assert r.status_code == 200 and r.json()["summary"] == {"client_shared": 2, "team": 0, "management": 1}

    result, job = publish_and_process(client, db, h["hamed"], vid)
    assert result["summary"]["management"] == 1 and job.outcome == "ready"

    assert all(x in visible(db, "u-hamed") for x in ("SPRINT8-DECISIONS", "SPRINT8-FEEDBACK", "SPRINT8-RISKS-MGMT"))
    sara, amina = visible(db, "u-sara"), visible(db, "u-amina")
    assert "SPRINT8-DECISIONS" in sara and "SPRINT8-RISKS-MGMT" not in sara
    assert "SPRINT8-FEEDBACK" in amina and "SPRINT8-RISKS-MGMT" not in amina
    assert "SPRINT8" not in visible(db, "u-youssef")                         # other project

    audit = db.execute("SELECT context, changed_by, new_visibility FROM visibility_changes WHERE version_id = %s",
                       (vid,)).fetchall()
    assert len(audit) == 3 and {a[0] for a in audit} == {"publish"} and {a[1] for a in audit} == {"u-hamed"}


def test_review_can_rename_merge_and_split_but_not_change_text(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    s = draft["sections"]
    merged = [{"heading": "Decisions & Feedback", "content": s[0]["content"] + "\n\n" + s[1]["content"],
               "visibility": "client_shared"},
              {"heading": "Risks", "content": s[2]["content"][:20], "visibility": "management"},
              {"heading": "Budget", "content": s[2]["content"][20:], "visibility": "management"}]
    r = client.put(f"/api/uploads/{vid}/sections", headers=h["hamed"], json={"sections": merged})
    assert r.status_code == 200 and [x["heading"] for x in r.json()["sections"]] == ["Decisions & Feedback", "Risks", "Budget"]

    tampered = [dict(x) for x in merged]
    tampered[0]["content"] += " Also, the contract is worth USD 9,999,999."
    r = client.put(f"/api/uploads/{vid}/sections", headers=h["hamed"], json={"sections": tampered})
    assert r.status_code == 422 and "can't be changed" in r.json()["detail"]
    bad_level = [dict(x, visibility="public") for x in merged]
    assert client.put(f"/api/uploads/{vid}/sections", headers=h["hamed"],
                      json={"sections": bad_level}).status_code == 422


def test_original_file_only_for_uploader_and_ceo(client, db, h):
    data = make_docx(SPRINT8)
    vid, _ = parsed_draft(client, db, h["hamed"], data)
    assert client.get(f"/api/uploads/{vid}/file", headers=h["hamed"]).content == data
    assert client.get(f"/api/uploads/{vid}/file", headers=h["mona"]).status_code == 200
    for other in ("sara", "amina", "omar"):
        assert client.get(f"/api/uploads/{vid}/file", headers=h[other]).status_code == 404


# --- New versions -------------------------------------------------------------------------------

def _live_doc(client, db, h, levels=None):
    vid, draft = parsed_draft(client, db, h["hamed"])
    set_levels(client, h["hamed"], vid, draft, levels or {"1. Decisions": "client_shared",
                                                          "3. Risks and Budget": "management"})
    publish_and_process(client, db, h["hamed"], vid)
    return draft["document_id"]


def test_new_version_reuses_levels_and_flags_changes(client, db, h):
    doc_id = _live_doc(client, db, h)
    v2 = {"1. Decisions": SPRINT8["1. Decisions"],                                   # unchanged
          "2. Demo Feedback": SPRINT8["2. Demo Feedback"] + " Second demo went well.",  # edited
          "3. Risks & Budget": SPRINT8["3. Risks and Budget"]}                         # renamed
    vid, draft = parsed_draft(client, db, h["hamed"], make_docx(v2), document_id=doc_id)
    by = {s["heading"]: s for s in draft["sections"]}
    assert draft["is_new_version"]
    assert (by["1. Decisions"]["visibility"], by["1. Decisions"]["changed"]) == ("client_shared", False)
    assert (by["2. Demo Feedback"]["visibility"], by["2. Demo Feedback"]["changed"]) == ("team", True)
    assert (by["3. Risks & Budget"]["visibility"], by["3. Risks & Budget"]["changed"]) == ("team", True)


def test_publishing_over_a_newer_version_is_blocked(client, db, h):
    doc_id = _live_doc(client, db, h)
    hamed_vid, _ = parsed_draft(client, db, h["hamed"], document_id=doc_id)
    mona_vid, _ = parsed_draft(client, db, h["mona"], document_id=doc_id)
    publish_and_process(client, db, h["mona"], mona_vid)
    r = client.post(f"/api/uploads/{hamed_vid}/publish", headers=h["hamed"])
    assert r.status_code == 409 and "Mona" in r.json()["detail"]


def test_permission_is_rechecked_at_publish(client, db, h):
    vid, _ = parsed_draft(client, db, h["hamed"])
    db.execute("DELETE FROM project_members WHERE user_id = 'u-hamed' AND project_id = 'P001'")
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 403
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["mona"]).status_code == 200   # CEO can


# --- Fixing mistakes ----------------------------------------------------------------------------

def test_live_visibility_change_applies_immediately(client, db, h):
    doc_id = _live_doc(client, db, h)
    assert "SPRINT8-RISKS-MGMT" not in visible(db, "u-amina")
    risks = next(s for s in client.get("/api/documents/manage", headers=h["hamed"]).json()["items"]
                 if s["id"] == doc_id)["sections"][2]
    r = client.patch(f"/api/documents/{doc_id}/sections/{risks['ordinal']}", headers=h["hamed"],
                     json={"visibility": "client_shared"})
    assert r.status_code == 200 and r.json()["previous"] == "management"
    assert "SPRINT8-RISKS-MGMT" in visible(db, "u-amina")
    client.patch(f"/api/documents/{doc_id}/sections/{risks['ordinal']}", headers=h["hamed"],
                 json={"visibility": "management"})
    assert "SPRINT8-RISKS-MGMT" not in visible(db, "u-amina")
    contexts = [r[0] for r in db.execute(
        "SELECT context FROM visibility_changes WHERE document_id = %s AND context = 'live_edit'", (doc_id,))]
    assert len(contexts) == 2
    assert client.patch(f"/api/documents/{doc_id}/sections/0", headers=h["sara"],
                        json={"visibility": "client_shared"}).status_code == 404


def test_restore_previous_version(client, db, h):
    doc_id = _live_doc(client, db, h)
    v2 = dict(SPRINT8, **{"1. Decisions": "SPRINT8-V2-ONLY decisions were revised."})
    vid, draft = parsed_draft(client, db, h["hamed"], make_docx(v2), document_id=doc_id)
    publish_and_process(client, db, h["hamed"], vid)
    assert "SPRINT8-V2-ONLY" in visible(db, "u-hamed") and "SPRINT8-DECISIONS" not in visible(db, "u-hamed")
    r = client.post(f"/api/documents/{doc_id}/restore-previous", headers=h["hamed"])
    assert r.status_code == 200
    assert "SPRINT8-DECISIONS" in visible(db, "u-hamed") and "SPRINT8-V2-ONLY" not in visible(db, "u-hamed")


def test_discard_and_expiry_remove_never_published_documents(client, db, h):
    data = make_docx(SPRINT8, title="Unique discard test")
    vid, draft = parsed_draft(client, db, h["hamed"], data)
    key = db.execute("SELECT file_key FROM document_versions WHERE id = %s", (vid,)).fetchone()[0]
    assert app.state.storage.path(key).exists()
    assert client.post(f"/api/uploads/{vid}/discard", headers=h["hamed"]).status_code == 204
    assert db.execute("SELECT count(*) FROM documents WHERE id = %s", (draft["document_id"],)).fetchone()[0] == 0
    assert not app.state.storage.path(key).exists()                       # orphaned original deleted

    vid2, draft2 = parsed_draft(client, db, h["hamed"], data)
    db.execute("UPDATE document_versions SET draft_expires_at = now() - interval '1 minute' WHERE id = %s", (vid2,))
    assert expire_drafts(db, app.state.storage) == 1
    assert db.execute("SELECT count(*) FROM documents WHERE id = %s", (draft2["document_id"],)).fetchone()[0] == 0
    assert not app.state.storage.path(key).exists()


def test_discarding_a_new_version_keeps_the_live_document(client, db, h):
    doc_id = _live_doc(client, db, h)
    vid, _ = parsed_draft(client, db, h["hamed"], document_id=doc_id)
    assert client.post(f"/api/uploads/{vid}/discard", headers=h["hamed"]).status_code == 204
    assert "SPRINT8-DECISIONS" in visible(db, "u-hamed")


# --- Failures and limits ------------------------------------------------------------------------

def test_scanned_pdf_fails_with_a_clear_message(client, db, h):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 50, 400, 600, fill=1)
    c.showPage()
    c.save()
    vid = upload(client, h["hamed"], buf.getvalue(), name="scan.pdf").json()["id"]
    assert parse_next(db, app.state.storage) == (vid, "failed")
    item = next(i for i in client.get("/api/uploads", headers=h["hamed"]).json()["items"] if i["id"] == vid)
    assert "no text layer" in item["error"]
    assert client.post(f"/api/uploads/{vid}/discard", headers=h["hamed"]).status_code == 204


def test_per_user_parsing_limit(client, db, h):
    for _ in range(5):
        assert upload(client, h["hamed"], make_docx(SPRINT8)).status_code == 202
    assert upload(client, h["hamed"], make_docx(SPRINT8)).status_code == 429
    while parse_next(db, app.state.storage):
        pass


def test_failed_publish_can_be_retried_and_old_version_stays_live(client, db, h):
    doc_id = _live_doc(client, db, h)
    v2 = dict(SPRINT8, **{"1. Decisions": "SPRINT8-V2-ONLY revised."})
    vid, _ = parsed_draft(client, db, h["hamed"], make_docx(v2), document_id=doc_id)
    client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"])
    for _ in range(3):
        db.execute("UPDATE document_versions SET next_attempt_at = now() WHERE id = %s", (vid,))
        process_next(db, FailingEmbedder())
    assert client.get(f"/api/uploads/{vid}", headers=h["hamed"]).json()["status"] == "failed"
    assert "SPRINT8-DECISIONS" in visible(db, "u-hamed")                      # v1 still live
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 200
    assert process_next(db, EMB).outcome == "ready"
    assert "SPRINT8-V2-ONLY" in visible(db, "u-hamed")


def test_pdf_upload_round_trip(client, db, h, tmp_path):
    from app.documents import load_documents
    from app.seed import DOCUMENTS_DIR
    from .render_docs import to_pdf
    qa = next(d for d in load_documents(DOCUMENTS_DIR) if d.id == "p001-qa-report")
    pdf = to_pdf(qa, tmp_path / "qa.pdf").read_bytes()
    vid, draft = parsed_draft(client, db, h["hamed"], pdf, name="QA report.pdf", doc_type="qa", title="QA re-upload")
    assert draft["kind"] == "pdf" and [s["heading"] for s in draft["sections"]] == [s.heading for s in qa.sections]
