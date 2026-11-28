"""Hand-labelled expected metadata for the 9 Nexora samples (+ 3 perturbed cases).

Values follow the wayfinder decisions: roles are mapped onto OUR role keys (W-03: ceo, pm, developer,
qa, finance, legal, operations, client); names we don't have are "unknown roles" (flagged, never
granted); classification is normalised (W-04); sharing rules are scored only on what we act on —
does a sentence restrict money information (W-05 → Internal finance), and does anything need a
review note (W-02 simplified).

``restricts_money=None`` means "genuinely ambiguous — not scored".
"""

SAMPLES = "/Users/mohamedhamed/Downloads/Nexora_Permission_RAG_Sample_Documents"

TRUTH = {
    "BRD-P001-001": dict(project_id="P001", project_name="E-Commerce Platform", document_type="brd",
                         classification="internal", owner="Product Manager",
                         authorized_roles={"ceo", "pm", "developer", "qa"}, unknown_roles=set(),
                         has_role_qualifier=True, restricts_money=True, needs_review_note=True),
    "PRD-P001-002": dict(project_id="P001", project_name="E-Commerce Platform", document_type="prd",
                         classification="confidential", owner="Product Manager",
                         authorized_roles={"ceo", "pm", "developer", "qa"}, unknown_roles=set(),
                         has_role_qualifier=False, restricts_money=False, needs_review_note=True),
    "Proposal-P001-003": dict(project_id="P001", project_name="E-Commerce Platform", document_type="proposal",
                              classification="commercial_confidential", owner="Account Director",
                              authorized_roles={"ceo", "pm", "finance", "legal"}, unknown_roles=set(),
                              has_role_qualifier=False, restricts_money=True, needs_review_note=True),
    "BRD-P002-004": dict(project_id="P002", project_name="Droop LMS", document_type="brd",
                         classification="internal", owner="Business Analyst",
                         authorized_roles={"ceo", "pm", "developer", "qa"}, unknown_roles={"instructor"},
                         has_role_qualifier=True, restricts_money=False, needs_review_note=True),
    "PRD-P002-005": dict(project_id="P002", project_name="Droop LMS", document_type="prd",
                         classification="confidential", owner="Product Owner",
                         authorized_roles={"ceo", "pm", "developer", "qa"}, unknown_roles={"instructor"},
                         has_role_qualifier=False, restricts_money=False, needs_review_note=True),
    "Proposal-P002-006": dict(project_id="P002", project_name="Droop LMS", document_type="proposal",
                              classification="commercial_confidential", owner="Account Director",
                              authorized_roles={"ceo", "pm", "finance", "legal"}, unknown_roles=set(),
                              has_role_qualifier=False, restricts_money=True, needs_review_note=True),
    "BRD-P003-007": dict(project_id="P003", project_name="Hub Drives", document_type="brd",
                         classification="internal", owner="Business Analyst",
                         authorized_roles={"ceo", "pm", "developer", "qa"}, unknown_roles={"vendor"},
                         has_role_qualifier=True, restricts_money=True, needs_review_note=True),
    "PRD-P003-008": dict(project_id="P003", project_name="Hub Drives", document_type="prd",
                         classification="confidential", owner="Product Owner",
                         authorized_roles={"ceo", "pm", "developer", "qa", "operations"}, unknown_roles=set(),
                         has_role_qualifier=False, restricts_money=None, needs_review_note=True),
    "Proposal-P003-009": dict(project_id="P003", project_name="Hub Drives", document_type="proposal",
                              classification="commercial_confidential", owner="Account Director",
                              authorized_roles={"ceo", "pm", "finance", "legal"}, unknown_roles=set(),
                              has_role_qualifier=False, restricts_money=True, needs_review_note=True),
}

# Perturbed cases: (source id, text transform, expected overrides). They test the W-04 fail-safe rules.
PERTURBED = {
    "typo-classification": ("PRD-P001-002",
                            lambda t: t.replace("Classification:** Confidential", "Classification:** Confidental"),
                            dict(classification="unknown")),
    "missing-roles": ("BRD-P001-001",
                      lambda t: "\n".join(l for l in t.splitlines() if "Authorized Roles" not in l),
                      dict(authorized_roles=None, has_role_qualifier=False)),
    "missing-classification": ("Proposal-P002-006",
                               lambda t: "\n".join(l for l in t.splitlines() if "Classification" not in l),
                               dict(classification="missing")),
}

# Held-out headers written AFTER the extractors were built, with wording the samples don't use.
# They measure how well each method generalises (the 9 samples were seen while writing the parser).
HELDOUT = {
    "H1-synonyms": ("""# PRD: Payments Module
Document ID: PRD-P009-101
Project ID: P009
Project: Payments Hub
Document Type: PRD
Classification: CONFIDENTIAL
Owner: Head of Product
Authorised roles: Project Manager, Developers, QA Engineers
Sharing Rules: Rates and margins must not be shared with clients.

## Scope
Card payments only.""", dict(document_id="PRD-P009-101", project_id="P009", project_name="Payments Hub",
        document_type="prd", classification="confidential", owner="Head of Product",
        authorized_roles={"pm", "developer", "qa"}, unknown_roles=set(), has_role_qualifier=False,
        restricts_money=True, needs_review_note=False)),
    "H2-table-other-keys": ("""# Proposal: Data Platform
| Field | Value |
| --- | --- |
| Reference | Proposal-P011-301 |
| Project ID | P011 |
| Project | Data Platform |
| Security Classification | Commercial Confidential |
| Access | CEO, Finance Manager, Legal Counsel |
| Sharing | Internal only. |

## Pricing
USD 40,000.""", dict(document_id="Proposal-P011-301", project_id="P011", project_name="Data Platform",
        document_type="proposal", classification="commercial_confidential", owner=None,
        authorized_roles={"ceo", "finance", "legal"}, unknown_roles=set(), has_role_qualifier=False,
        restricts_money=False, needs_review_note=True)),
    "H3-unknown-level-and-role": ("""# BRD: Warehouse Robots
- **Document ID:** BRD-P012-401
- **Project ID:** P012
- **Project:** Warehouse Robots
- **Document Type:** BRD
- **Classification:** Restricted
- **Document Owner:** Business Analyst
- **Authorized Roles:** CEO, Project Manager, Architect
- **Sharing Rules:** Budget figures are restricted to CEO and Finance.

## Goals
Automate picking.""", dict(document_id="BRD-P012-401", project_id="P012", project_name="Warehouse Robots",
        document_type="brd", classification="unknown", owner="Business Analyst",
        authorized_roles={"ceo", "pm"}, unknown_roles={"architect"}, has_role_qualifier=False,
        restricts_money=True, needs_review_note=False)),
    "H4-prose-header": ("""# BRD: Fleet Tracker
This document (ID BRD-P010-201) for project P010 Fleet Tracker is classified Internal and may be read by
the CEO, the project manager and the QA team. Owner: Operations Lead.

## Background
Track delivery vans.""", dict(document_id="BRD-P010-201", project_id="P010", project_name="Fleet Tracker",
        document_type="brd", classification="internal", owner="Operations Lead",
        authorized_roles={"ceo", "pm", "qa"}, unknown_roles=set(), has_role_qualifier=False,
        restricts_money=False, needs_review_note=False)),
}
