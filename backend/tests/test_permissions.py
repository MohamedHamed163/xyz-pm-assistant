"""The role × document type × topic table, checked marker by marker.

Every sample document carries one marker per topic (e.g. ``DBRD-RULE`` sits in the Droob BRD's
Business Rules). ``ROLE_TABLE`` below is the user's table written out by hand — independently of
company.yaml — so a mistake in the YAML rules shows up here.
"""

import re

import pytest

from app.policy import AccessScope, User, build_scope, filter_chunks

# marker → (project, doc_type, topic)
MARKERS = {
    "DBRD-DET": ("P001", "brd", "details"), "DBRD-CTX": ("P001", "brd", "context"),
    "DBRD-GOAL": ("P001", "brd", "goals"), "DBRD-REQ": ("P001", "brd", "requirements"),
    "DBRD-RULE": ("P001", "brd", "business_rules"), "DBRD-PLAN": ("P001", "brd", "planning"),
    "DBRD-RISK": ("P001", "brd", "risks"), "DBRD-GOV": ("P001", "brd", "governance"),
    "DBRD-COM": ("P001", "brd", "commercial"),
    "DPRD-DET": ("P001", "prd", "details"), "DPRD-OVR": ("P001", "prd", "overview"),
    "DPRD-SCP": ("P001", "prd", "scope"), "DPRD-REQ": ("P001", "prd", "requirements"),
    "DPRD-DLV": ("P001", "prd", "delivery"),
    "DPRP-DET": ("P001", "proposal", "details"), "DPRP-SUM": ("P001", "proposal", "summary"),
    "DPRP-COM1": ("P001", "proposal", "commercial"), "DPRP-SCP": ("P001", "proposal", "scope"),
    "DPRP-COM2": ("P001", "proposal", "commercial"), "DPRP-TML": ("P001", "proposal", "timeline"),
    "DPRP-COM": ("P001", "proposal", "commercial"), "DPRP-ENG": ("P001", "proposal", "engagement"),
    "DPRP-CMP": ("P001", "proposal", "completion"),
    "HBRD-DET": ("P002", "brd", "details"), "HBRD-CTX": ("P002", "brd", "context"),
    "HBRD-GOAL": ("P002", "brd", "goals"), "HBRD-REQ": ("P002", "brd", "requirements"),
    "HBRD-RULE": ("P002", "brd", "business_rules"), "HBRD-COM": ("P002", "brd", "commercial"),
    "HBRD-RISK": ("P002", "brd", "risks"),
    "HPRD-DET": ("P002", "prd", "details"), "HPRD-OVR": ("P002", "prd", "overview"),
    "HPRD-SCP": ("P002", "prd", "scope"), "HPRD-REQ": ("P002", "prd", "requirements"),
    "HPRD-DLV": ("P002", "prd", "delivery"),
    "HPRP-DET": ("P002", "proposal", "details"), "HPRP-SUM": ("P002", "proposal", "summary"),
    "HPRP-SCP": ("P002", "proposal", "scope"), "HPRP-TML": ("P002", "proposal", "timeline"),
    "HPRP-COM": ("P002", "proposal", "commercial"), "HPRP-CMP": ("P002", "proposal", "completion"),
}

ALL = "*"
# The user's table (design review 2026-11-25), plus "details" for anyone who may read any part.
ROLE_TABLE = {
    "ceo": {"brd": ALL, "prd": ALL, "proposal": ALL},
    "pm": {"brd": ALL, "prd": ALL, "proposal": ALL},
    "client": {"brd": ALL, "prd": ALL, "proposal": ALL},
    "developer": {"brd": {"details", "context", "requirements"},
                  "prd": {"details", "overview", "scope", "requirements", "delivery"},
                  "proposal": {"details", "scope", "timeline"}},
    "qa": {"brd": {"details", "goals", "business_rules"},
           "prd": {"details", "overview", "scope", "requirements", "delivery"},
           "proposal": {"details", "scope", "completion"}},
    "finance": {"brd": {"details", "goals", "commercial"},
                "prd": {"details", "overview", "scope", "commercial"},
                "proposal": ALL},
}

USERS = {"Mona": ("ceo", {"P001", "P002"}), "Hamed": ("pm", {"P001"}), "Sara": ("developer", {"P001"}),
         "Omar": ("qa", {"P001"}), "Khaled": ("finance", {"P001"}), "Amina": ("client", {"P001"}),
         "Youssef": ("developer", {"P002"})}


def expected(name: str) -> set[str]:
    role, projects = USERS[name]
    out = set()
    for marker, (project, doc_type, topic) in MARKERS.items():
        allowed = ROLE_TABLE[role][doc_type]
        if project in projects and (allowed == ALL or topic in allowed):
            out.add(marker)
    return out


def found(text: str) -> set[str]:
    return set(re.findall(r"\b[DH](?:BRD|PRD|PRP)-[A-Z0-9]+\b", text)) & set(MARKERS)


def test_every_marker_is_in_the_corpus(chunks):
    assert found("\n".join(c.text for c in chunks)) == set(MARKERS)


def test_markers_sit_in_their_topic(chunks):
    for c in chunks:
        for marker in found(c.text):
            project, doc_type, topic = MARKERS[marker]
            assert (c.project_id, c.doc_type, c.topic) == (project, doc_type, topic), marker


@pytest.mark.parametrize("name", sorted(USERS))
def test_role_table(visible_text, name):
    sees = found(visible_text(name))
    assert sees == expected(name), f"{name}: extra {sorted(sees - expected(name))}, missing {sorted(expected(name) - sees)}"


# --- The examples from the brief ----------------------------------------------------------------

def test_qa_sees_only_rules_and_objectives_of_the_brd(visible_text):
    text = visible_text("Omar")
    assert "DBRD-RULE" in text and "DBRD-GOAL" in text
    assert not any(m in text for m in ("DBRD-CTX", "DBRD-REQ", "DBRD-GOV", "DBRD-RISK", "DBRD-COM"))


def test_qa_sees_scope_and_acceptance_of_the_proposal_but_no_prices(visible_text):
    text = visible_text("Omar")
    assert "DPRP-SCP" in text and "DPRP-CMP" in text
    assert not any(m in text for m in ("DPRP-COM", "DPRP-COM1", "DPRP-COM2", "$1,000", "$3,000"))


def test_price_inside_an_allowed_section_never_reaches_developers(visible_text):
    text = visible_text("Sara")
    assert "Plan 2 — AI Integration" in text                 # the plan's scope
    assert "Investment" not in text and "$" not in text       # its price was split out


def test_finance_reads_the_whole_proposal(visible_text):
    text = visible_text("Khaled")
    assert all(m in text for m in ("DPRP-COM", "DPRP-COM1", "DPRP-COM2", "DPRP-ENG"))
    assert "DPRD-REQ" not in text                              # PRD requirements aren't theirs


def test_other_project_is_invisible(visible_text):
    assert not any(m.startswith("D") for m in found(visible_text("Youssef")))
    assert not any(m.startswith("H") for m in found(visible_text("Sara")))


def test_stray_pdf_markup_is_removed(chunks):
    assert not any("<text" in c.text or "</text>" in c.text for c in chunks)


# --- Fail closed --------------------------------------------------------------------------------

def test_unknown_role_sees_nothing(company, chunks):
    ghost = User("u-ghost", "Ghost", "intern", "xyz", frozenset({"P001"}))
    assert filter_chunks(build_scope(ghost, company.role_policies), chunks) == []


def test_unclassified_is_ceo_and_pm_only(company):
    for role, policy in company.role_policies.items():
        has = any(k.endswith(":unclassified") for k in policy.access_keys)
        assert has == (role in {"ceo", "pm"}), role


def test_sql_values_are_parameters_not_inlined():
    scope = AccessScope("u", "xyz'; DROP TABLE chunks;--", False, frozenset({"P001"}), frozenset({"brd:goals"}))
    clause, params = scope.to_sql()
    assert "DROP TABLE" not in clause and params["company_id"].startswith("xyz'")
