"""Permission tests.

Each "canary" is a fact that appears in exactly one document section. If a user can retrieve the
canary, they can retrieve that section. This grid is the security regression suite: any change to
the policy, the seed data or the document markers that leaks content will flip a row.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.policy import AccessScope, Grant, User, build_scope, filter_chunks

from .conftest import NOW

# canary text -> where it lives
CANARIES = {
    "15-minute JWT": "P001 tech architecture / auth flow (internal)",
    "Shibboleth": "P002 API docs / auth flow (internal)",
    "2027-02-15": "P001 BRD / milestones (client_shared)",
    "Project Papyrus": "P001 BRD / internal risks (management)",
    "BUG-412": "P001 QA report (internal)",
    "AC-FR-02": "P001 PRD / acceptance criteria (internal)",
    "USD 486,000": "P001 contract / fees (client_shared, restricted doc)",
    "USD 352,000": "P001 contract / internal negotiation notes (management, restricted doc)",
    "31.4%": "Company profitability report (restricted, company-wide)",
    "BUG-HD-77": "P003 QA test cases (internal)",
    "LDAP bridge": "P002 BRD internal risks + profitability report",
}

# user -> canaries they MUST see. Everything else in CANARIES they must NOT see.
EXPECTED_VISIBLE = {
    "Hamed":   {"15-minute JWT", "2027-02-15", "Project Papyrus", "BUG-412", "AC-FR-02"},
    "Sara":    {"15-minute JWT", "2027-02-15", "BUG-412", "AC-FR-02"},        # team level: no management
    "Omar":    {"15-minute JWT", "2027-02-15", "BUG-412", "AC-FR-02"},
    "Youssef": {"Shibboleth", "LDAP bridge"},
    "Mona":    set(CANARIES),
    "Amina":   {"2027-02-15", "USD 486,000"},
    "Khaled":  {"USD 486,000", "USD 352,000", "31.4%", "LDAP bridge"},
}


@pytest.mark.parametrize("user", sorted(EXPECTED_VISIBLE))
@pytest.mark.parametrize("canary", sorted(CANARIES))
def test_canary_grid(visible_text, user, canary):
    should_see = canary in EXPECTED_VISIBLE[user]
    sees = canary in visible_text(user)
    assert sees == should_see, (
        f"{user} {'cannot' if should_see else 'CAN'} see '{canary}' ({CANARIES[canary]})"
    )


# --- The 7 acceptance scenarios from docs/business-scenario.md -------------------------------

def test_1_sara_gets_p001_auth_flow(visible_text):
    assert "7-day rotating refresh token" in visible_text("Sara")


def test_2_sara_gets_nothing_from_p002(company, chunks):
    sara = company.user_by_name("Sara")
    scope = build_scope(sara, company.role_policies, company.grants, now=NOW)
    assert not any(c.project_id == "P002" for c in filter_chunks(scope, chunks))


def test_3_hamed_gets_p001_milestones(visible_text):
    assert "Go-live (NRG Online public launch)" in visible_text("Hamed")


def test_4_hamed_blocked_from_contract_by_default(company, chunks):
    hamed = company.user_by_name("Hamed")
    scope = build_scope(hamed, company.role_policies, company.grants, now=NOW)
    assert not any(c.doc_type == "contract" for c in filter_chunks(scope, chunks))


def test_5_mona_gets_portfolio_financials(visible_text):
    text = visible_text("Mona")
    assert "Project Profitability" in text and "18.2%" in text


def test_6_amina_gets_delivery_timeline(visible_text):
    assert "Delivery Milestones" in visible_text("Amina")


def test_7_amina_gets_no_qa_content(company, chunks):
    amina = company.user_by_name("Amina")
    scope = build_scope(amina, company.role_policies, company.grants, now=NOW)
    visible = filter_chunks(scope, chunks)
    assert not any(c.doc_type in {"qa", "technical"} for c in visible)
    assert all(c.visibility == "client_shared" for c in visible)


# --- Grants, expiry, revocation -----------------------------------------------------------------

def test_grant_on_contract_opens_it_for_hamed(company, chunks):
    hamed = company.user_by_name("Hamed")
    grants = company.grants + (Grant(hamed.id, "p001-client-contract"),)
    scope = build_scope(hamed, company.role_policies, grants, now=NOW)
    texts = "\n".join(c.text for c in filter_chunks(scope, chunks))
    assert "USD 486,000" in texts


def test_revoking_a_grant_takes_effect_on_next_scope_build(company, chunks):
    amina = company.user_by_name("Amina")
    without_amina = tuple(g for g in company.grants if g.user_id != amina.id)
    scope = build_scope(amina, company.role_policies, without_amina, now=NOW)
    assert not any(c.doc_type == "contract" for c in filter_chunks(scope, chunks))


def test_expired_grant_is_ignored(company, chunks):
    hamed = company.user_by_name("Hamed")
    expired = Grant(hamed.id, "p001-client-contract", expires_at=NOW - timedelta(seconds=1))
    scope = build_scope(hamed, company.role_policies, company.grants + (expired,), now=NOW)
    assert "p001-client-contract" not in scope.granted_document_ids


def test_grant_never_bypasses_client_shared_only(company, chunks):
    amina = company.user_by_name("Amina")
    grants = company.grants + (Grant(amina.id, "p001-qa-report"), Grant(amina.id, "p001-brd"))
    scope = build_scope(amina, company.role_policies, grants, now=NOW)
    visible = filter_chunks(scope, chunks)
    assert all(c.visibility == "client_shared" for c in visible)
    assert not any("BUG-412" in c.text or "Project Papyrus" in c.text for c in visible)


# --- Fail-closed behaviour ----------------------------------------------------------------------

def test_project_reassignment_takes_effect_immediately(company, chunks):
    hamed = company.user_by_name("Hamed")
    moved = replace(hamed, projects=frozenset({"P002"}))
    scope = build_scope(moved, company.role_policies, company.grants, now=NOW)
    projects = {c.project_id for c in filter_chunks(scope, chunks)}
    assert projects == {"P002"}


def test_unknown_role_sees_nothing(company, chunks):
    ghost = User("u-ghost", "Ghost", "intern", "xyz", frozenset({"P001"}))
    scope = build_scope(ghost, company.role_policies, company.grants, now=NOW)
    assert filter_chunks(scope, chunks) == []


def test_documents_still_processing_are_invisible_even_to_ceo(company, chunks):
    mona = company.user_by_name("Mona")
    scope = build_scope(mona, company.role_policies, company.grants, now=NOW)
    processing = [replace(c, status="processing") for c in chunks]
    assert filter_chunks(scope, processing) == []


def test_other_company_is_invisible_even_to_ceo(company, chunks):
    mona = company.user_by_name("Mona")
    scope = build_scope(mona, company.role_policies, company.grants, now=NOW)
    foreign = [replace(c, company_id="other-co") for c in chunks]
    assert filter_chunks(scope, foreign) == []


def test_company_wide_docs_need_company_scope_or_grant(company, chunks):
    for name in ("Hamed", "Sara", "Omar", "Youssef", "Amina"):
        user = company.user_by_name(name)
        scope = build_scope(user, company.role_policies, company.grants, now=NOW)
        assert not any(c.project_id is None for c in filter_chunks(scope, chunks)), name


# --- SQL rendering ------------------------------------------------------------------------------

def test_sql_for_client_adds_visibility_filter(company):
    amina = company.user_by_name("Amina")
    clause, params = build_scope(amina, company.role_policies, company.grants, now=NOW).to_sql()
    assert "visibility = 'client_shared'" in clause
    assert params["project_ids"] == ["P001"]
    assert params["granted_document_ids"] == ["p001-client-contract"]
    assert params["company_wide"] is False


def test_sql_for_ceo_is_company_wide_not_a_document_list(company):
    mona = company.user_by_name("Mona")
    clause, params = build_scope(mona, company.role_policies, company.grants, now=NOW).to_sql()
    assert params["company_wide"] is True
    assert params["granted_document_ids"] == []
    assert params["role_levels"] == ["client_shared", "team", "management"]
    assert not clause.endswith("AND chunks.visibility = 'client_shared'")   # no client cap


def test_sql_values_are_parameters_not_inlined(company):
    scope = AccessScope("u", "xyz'; DROP TABLE chunks;--", False, frozenset({"P001"}),
                        frozenset({"brd"}), frozenset(), False)
    clause, params = scope.to_sql()
    assert "DROP TABLE" not in clause
    assert params["company_id"].startswith("xyz'")


# --- Section levels -----------------------------------------------------------------------------

def _texts(company, chunks, user, grants=None):
    u = company.users[user] if user.startswith("u-") else company.user_by_name(user)
    scope = build_scope(u, company.role_policies, company.grants if grants is None else grants, now=NOW)
    return "\n".join(c.text for c in filter_chunks(scope, chunks))


def test_management_sections_are_hidden_from_developers_and_qa(company, chunks):
    for name in ("Sara", "Omar"):
        assert "Project Papyrus" not in _texts(company, chunks, name)
    assert "Project Papyrus" in _texts(company, chunks, "Hamed")


def test_grant_level_limits_what_a_grant_opens(company, chunks):
    hamed = company.user_by_name("Hamed")
    team = company.grants + (Grant(hamed.id, "p001-client-contract", max_visibility="team"),)
    text = _texts(company, chunks, "Hamed", team)
    # PMs can't read contracts by role, so only the grant applies — and it stops at team.
    assert "USD 486,000" in text and "USD 352,000" not in text
    sara = company.user_by_name("Sara")
    team = company.grants + (Grant(sara.id, "p001-client-contract", max_visibility="team"),)
    text = _texts(company, chunks, "Sara", team)
    assert "USD 486,000" in text and "USD 352,000" not in text      # team grant: no negotiation notes
    shared = company.grants + (Grant(sara.id, "p001-client-contract", max_visibility="client_shared"),)
    text = _texts(company, chunks, "Sara", shared)
    assert "1. Parties" in text and "USD 486,000" in text and "USD 352,000" not in text


def test_management_grant_never_lifts_the_client_cap(company, chunks):
    amina = company.user_by_name("Amina")
    grants = tuple(g for g in company.grants if g.user_id != amina.id) + (
        Grant(amina.id, "p001-client-contract", max_visibility="management"),
        Grant(amina.id, "p001-qa-report", max_visibility="management"),
    )
    text = _texts(company, chunks, "Amina", grants)
    assert "USD 486,000" in text and "USD 352,000" not in text and "BUG-412" not in text


def test_grant_level_does_not_lower_role_level(company, chunks):
    """A low-level grant on a document the role already reads must not hide sections."""
    hamed = company.user_by_name("Hamed")
    grants = company.grants + (Grant(hamed.id, "p001-brd", max_visibility="client_shared"),)
    assert "Project Papyrus" in _texts(company, chunks, "Hamed", grants)
