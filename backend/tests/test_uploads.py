"""Upload → auto-topics → review → publish, end to end through the HTTP API."""

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
EMAILS = {"hamed": "hamed@xyz.test", "sara": "sara@xyz.test", "mona": "mona@xyz.test", "omar": "omar@xyz.test",
          "amina": "amina@droob.test", "khaled": "khaled@xyz.test", "youssef": "youssef@xyz.test"}


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


# A small BRD in Word, like a real one: title, a contents list, numbered headings, one odd heading.
BRD = {
    "4. Business Goals & Objectives": "UPL-GOAL raise weekly study sessions by 25%.",
    "11. Business Rules": "UPL-RULE one active session per device.",
    "13. Constraints": "UPL-PLAN limited pilot scope.\nPilot budget: USD 2,500 for hosting (UPL-COM).",
    "Appendix Z — Glossary": "UPL-ODD terms used in this document.",
}


def make_docx(sections: dict[str, str], title="Droob AI — BRD v2") -> bytes:
    d = Document()
    d.add_paragraph(title, style="Title")
    d.add_paragraph("Contents")
    for n, heading in enumerate(sections, start=1):
        d.add_paragraph(f"{heading} .......... {n + 1}")
    for heading, body in sections.items():
        d.add_paragraph(heading, style="Heading 2")
        for line in body.split("\n"):
            d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload(client, headers, data: bytes, name="BRD v2.docx", **form):
    form = {"doc_type": "brd", "project_id": "P001", "title": "Droob AI — BRD v2"} | form
    return client.post("/api/uploads", headers=headers, files={"file": (name, data)}, data=form)


def parsed_draft(client, db, headers, data=None, **form):
    r = upload(client, headers, data or make_docx(BRD), **form)
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    assert parse_next(db, app.state.storage) == (vid, "draft")
    return vid, client.get(f"/api/uploads/{vid}", headers=headers).json()


def classify_all(client, headers, vid, draft, topic_for_unclassified="governance"):
    sections = [{"heading": s["heading"], "content": s["content"],
                 "topic": topic_for_unclassified if s["topic"] == "unclassified" else s["topic"]}
                for s in draft["sections"]]
    return client.put(f"/api/uploads/{vid}/sections", headers=headers,
                      json={"sections": sections, "lock_version": draft["lock_version"]})


def live_doc(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    assert classify_all(client, h["hamed"], vid, draft).status_code == 200
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 200
    assert process_next(db, EMB).outcome == "ready"
    return draft["document_id"]


def visible(db, user_id) -> str:
    return "\n".join(c.content for c in retrieve(db, user_id, "goals rules", EMB, k=10_000, audit=False).chunks)


# --- Who may upload -----------------------------------------------------------------------------

@pytest.mark.parametrize("who,form,status", [
    ("hamed", {}, 202), ("hamed", {"doc_type": "proposal"}, 202),
    ("hamed", {"project_id": "P002"}, 403), ("hamed", {"project_id": ""}, 403),
    ("mona", {"project_id": "P002"}, 202), ("mona", {"doc_type": "minutes"}, 403),
    ("sara", {}, 403), ("omar", {}, 403), ("amina", {}, 403), ("khaled", {}, 403), ("youssef", {}, 403),
])
def test_upload_permissions(client, h, who, form, status):
    assert upload(client, h[who], make_docx(BRD), **form).status_code == status


def test_options_list_topics_and_who_reads_them(client, h):
    opts = client.get("/api/uploads/options", headers=h["hamed"]).json()
    assert [p["id"] for p in opts["projects"]] == ["P001"]
    assert {t["name"] for t in opts["doc_types"]} == {"brd", "prd", "proposal"}
    rules = next(t for t in opts["topics"]["brd"] if t["key"] == "business_rules")
    assert set(rules["roles"]) == {"CEO", "Project Manager", "Client", "QA Engineer"}


# --- Auto-topics, commercial split, review ------------------------------------------------------

def test_sections_are_tagged_automatically(client, db, h):
    _, draft = parsed_draft(client, db, h["hamed"])
    by = {s["heading"]: s["topic"] for s in draft["sections"]}
    assert by["4. Business Goals & Objectives"] == "goals"
    assert by["11. Business Rules"] == "business_rules"
    assert by["13. Constraints"] == "planning"
    assert by["Commercial details — from 13. Constraints"] == "commercial"
    assert by["Appendix Z — Glossary"] == "unclassified"
    assert draft["unclassified"] == 1
    constraints = next(s for s in draft["sections"] if s["heading"] == "13. Constraints")["content"]
    assert "USD" not in constraints                              # the price line moved out


def test_unclassified_blocks_publish_and_shows_in_review_requests(client, db, h):
    vid, draft = parsed_draft(client, db, h["mona"])           # the CEO uploads to P001
    r = client.post(f"/api/uploads/{vid}/publish", headers=h["mona"])
    assert r.status_code == 409 and "need a topic" in r.json()["detail"]
    # Any PM of the project (and the CEO) sees it — not the developer, not another project's people.
    assert vid in [i["id"] for i in client.get("/api/uploads/review-requests", headers=h["hamed"]).json()["items"]]
    for other in ("sara", "youssef"):
        assert client.get("/api/uploads/review-requests", headers=h[other]).json()["items"] == []
    # Hamed finishes Mona's draft.
    draft = client.get(f"/api/uploads/{vid}", headers=h["hamed"]).json()
    assert classify_all(client, h["hamed"], vid, draft).status_code == 200
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 200
    assert client.get("/api/uploads/review-requests", headers=h["hamed"]).json()["items"] == []


def test_published_upload_follows_the_role_table(client, db, h):
    live_doc(client, db, h)
    omar, sara, khaled = visible(db, "u-omar"), visible(db, "u-sara"), visible(db, "u-khaled")
    assert "UPL-RULE" in omar and "UPL-GOAL" in omar and "UPL-PLAN" not in omar and "UPL-COM" not in omar
    assert "UPL-RULE" not in sara and "UPL-GOAL" not in sara
    assert "UPL-COM" in khaled and "UPL-RULE" not in khaled
    assert "UPL-" not in visible(db, "u-youssef")


def test_draft_is_invisible_to_search(client, db, h):
    parsed_draft(client, db, h["hamed"])
    for user in ("u-mona", "u-hamed", "u-omar"):
        assert "UPL-" not in visible(db, user)


def test_review_may_move_lines_but_not_change_text(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    s = {x["heading"]: x for x in draft["sections"]}
    # Move the price line back into Constraints (a false alarm) — allowed: same lines, re-arranged.
    sections = [{"heading": x["heading"], "content": x["content"], "topic": x["topic"]}
                for x in draft["sections"] if not x["heading"].startswith("Commercial details")]
    for x in sections:
        if x["heading"] == "13. Constraints":
            x["content"] += "\n" + s["Commercial details — from 13. Constraints"]["content"]
    r = client.put(f"/api/uploads/{vid}/sections", headers=h["hamed"],
                   json={"sections": sections, "lock_version": draft["lock_version"]})
    assert r.status_code == 200
    tampered = [dict(x) for x in sections]
    tampered[0]["content"] += " Also, the budget is USD 9,999,999."
    r = client.put(f"/api/uploads/{vid}/sections", headers=h["hamed"],
                   json={"sections": tampered, "lock_version": r.json()["lock_version"]})
    assert r.status_code == 422 and "can't be changed" in r.json()["detail"]


def test_two_reviewers_cannot_overwrite_each_other(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    assert classify_all(client, h["mona"], vid, draft, "risks").status_code == 200          # Mona saves first
    r = classify_all(client, h["hamed"], vid, draft, "governance")                           # Hamed's copy is stale
    assert r.status_code == 409 and "Mona changed this draft" in r.json()["detail"]


def test_original_file_only_for_uploader_and_ceo(client, db, h):
    data = make_docx(BRD)
    vid, _ = parsed_draft(client, db, h["hamed"], data)
    assert client.get(f"/api/uploads/{vid}/file", headers=h["hamed"]).content == data
    assert client.get(f"/api/uploads/{vid}/file", headers=h["mona"]).status_code == 200
    for other in ("sara", "omar", "amina"):
        assert client.get(f"/api/uploads/{vid}/file", headers=h[other]).status_code == 404


# --- Live fixes, versions, failures -------------------------------------------------------------

def test_live_topic_change_applies_immediately(client, db, h):
    doc_id = live_doc(client, db, h)
    assert "UPL-ODD" not in visible(db, "u-omar")                # tagged governance: not QA's
    sections = next(d for d in client.get("/api/documents/manage", headers=h["hamed"]).json()["items"]
                    if d["id"] == doc_id)["sections"]
    odd = next(s for s in sections if s["heading"].startswith("Appendix Z"))
    r = client.patch(f"/api/documents/{doc_id}/sections/{odd['ordinal']}", headers=h["hamed"],
                     json={"topic": "business_rules"})
    assert r.status_code == 200 and r.json()["previous"] == "governance"
    assert "UPL-ODD" in visible(db, "u-omar")
    assert client.patch(f"/api/documents/{doc_id}/sections/0", headers=h["sara"],
                        json={"topic": "context"}).status_code == 404
    assert db.execute("SELECT count(*) FROM topic_changes WHERE document_id = %s AND context = 'live_edit'",
                      (doc_id,)).fetchone()[0] == 1


def test_new_version_reuses_topics_and_restore_works(client, db, h):
    doc_id = live_doc(client, db, h)
    v2 = dict(BRD, **{"11. Business Rules": "UPL-RULE-V2 two sessions per device."})
    vid, draft = parsed_draft(client, db, h["hamed"], make_docx(v2), document_id=doc_id)
    by = {s["heading"]: s for s in draft["sections"]}
    assert by["Appendix Z — Glossary"]["topic"] == "governance"           # reused from v1, not unclassified
    assert by["11. Business Rules"]["changed"] and not by["4. Business Goals & Objectives"]["changed"]
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 200
    process_next(db, EMB)
    assert "UPL-RULE-V2" in visible(db, "u-omar")
    assert client.post(f"/api/documents/{doc_id}/restore-previous", headers=h["hamed"]).status_code == 200
    assert "UPL-RULE-V2" not in visible(db, "u-omar") and "UPL-RULE" in visible(db, "u-omar")


def test_permission_is_rechecked_at_publish(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    classify_all(client, h["hamed"], vid, draft)
    db.execute("DELETE FROM project_members WHERE user_id = 'u-hamed' AND project_id = 'P001'")
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code in (403, 404)
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["mona"]).status_code == 200


def test_failed_publish_can_be_retried(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    classify_all(client, h["hamed"], vid, draft)
    client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"])
    for _ in range(3):
        db.execute("UPDATE document_versions SET next_attempt_at = now() WHERE id = %s", (vid,))
        process_next(db, FailingEmbedder())
    assert client.get(f"/api/uploads/{vid}", headers=h["hamed"]).json()["status"] == "failed"
    assert client.post(f"/api/uploads/{vid}/publish", headers=h["hamed"]).status_code == 200
    assert process_next(db, EMB).outcome == "ready"


def test_discard_and_expiry(client, db, h):
    vid, draft = parsed_draft(client, db, h["hamed"])
    assert client.post(f"/api/uploads/{vid}/discard", headers=h["hamed"]).status_code == 204
    assert db.execute("SELECT count(*) FROM documents WHERE id = %s", (draft["document_id"],)).fetchone()[0] == 0
    vid2, draft2 = parsed_draft(client, db, h["hamed"])
    db.execute("UPDATE document_versions SET draft_expires_at = now() - interval '1 minute' WHERE id = %s", (vid2,))
    assert expire_drafts(db, app.state.storage) == 1


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


def test_file_type_and_size_are_checked(client, h):
    assert upload(client, h["hamed"], b"MZ\x90\x00 not a document", name="report.pdf").status_code == 400
    assert upload(client, h["hamed"], b"%PDF-" + b"0" * (21 * 1024 * 1024)).status_code == 413


def test_pdf_proposal_round_trip_splits_prices(client, db, h, tmp_path):
    from app.documents import load_documents
    from app.seed import DOCUMENTS_DIR
    from .render_docs import to_pdf
    proposal = next(d for d in load_documents(DOCUMENTS_DIR) if d.id == "droob-proposal")
    pdf = to_pdf(proposal, tmp_path / "proposal.pdf").read_bytes()
    _, draft = parsed_draft(client, db, h["hamed"], pdf, name="Proposal.pdf", doc_type="proposal", title="Proposal")
    by = {s["heading"]: s["topic"] for s in draft["sections"]}
    assert by["4. Project Delivery Plans"] == "scope" and by["6. Commercial Proposal"] == "commercial"
    plans = next(s for s in draft["sections"] if s["heading"] == "4. Project Delivery Plans")["content"]
    assert "$" not in plans and draft["unclassified"] == 0
