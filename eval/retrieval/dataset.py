"""W-01 evaluation dataset over the 9 Nexora sample documents.

QUESTIONS: (id, question, [acceptable (doc_id, section heading)], [facts])
  - facts are short case-insensitive strings; "a|b" means either is fine. An answer is correct when every
    fact appears in it. A question with no sections has NO answer in the corpus (expected: not found).
SECTION_READERS: who SHOULD be able to read each section under the agreed target policy
  (wayfinder decisions W-02…W-13): role table ∩ document ceiling (Authorized Roles ∩ classification) ∩
  section restriction (Pricing / Internal finance). Project membership is applied on top (CEO: all).
  Legal and Operations are left out: they don't exist in the current system, so they can't be baselined.
"""

BRD1, PRD1, PRP1 = "brd-p001-001", "prd-p001-002", "proposal-p001-003"
BRD2, PRD2, PRP2 = "brd-p002-004", "prd-p002-005", "proposal-p002-006"
BRD3, PRD3, PRP3 = "brd-p003-007", "prd-p003-008", "proposal-p003-009"

PROJECT = {d: "P00" + d.split("-p00")[1][0] for d in
           (BRD1, PRD1, PRP1, BRD2, PRD2, PRP2, BRD3, PRD3, PRP3)}

_CP, _CPD, _CPQ = {"ceo", "pm"}, {"ceo", "pm", "developer"}, {"ceo", "pm", "qa"}
_TEAM = {"ceo", "pm", "developer", "qa"}
_COM, _FIN = {"ceo", "pm", "finance"}, {"ceo", "finance"}

SECTION_READERS = {
    # BRDs — ceiling CEO/PM/Dev/QA (Authorized Roles ∩ Internal); topics: Dev context+requirements, QA goals
    (BRD1, "Introduction"): _TEAM, (BRD1, "Background"): _CPD, (BRD1, "Business Objectives"): _CPQ,
    (BRD1, "Requirements"): _CPD, (BRD1, "Constraints"): _CP, (BRD1, "Stakeholders"): _CP,
    (BRD2, "Introduction"): _TEAM, (BRD2, "Business Goal"): _CPQ, (BRD2, "Business Requirements"): _CPD,
    (BRD2, "Success Metrics"): _CPQ, (BRD2, "Stakeholders"): _CP,
    (BRD3, "Introduction"): _TEAM, (BRD3, "Business Goal"): _CPQ, (BRD3, "Business Requirements"): _CPD,
    (BRD3, "Stakeholders"): _CP, (BRD3, "Success Metrics"): _CPQ,
    # PRDs — ceiling CEO/PM/Dev/QA (∩ Confidential); every section is scope/requirements (W-06, W-13)
    **{(PRD1, h): _TEAM for h in ("Introduction", "Scope", "User Stories", "Acceptance Criteria",
                                  "Non-Functional", "Admin-only feature")},
    **{(PRD2, h): _TEAM for h in ("Introduction", "Features", "User Stories", "Restricted Content",
                                  "Acceptance Criteria")},
    **{(PRD3, h): _TEAM for h in ("Introduction", "Features", "User Stories", "Access Rules",
                                  "Acceptance Criteria")},
    # Proposals — ceiling CEO/PM/Finance(/Legal); internal notes → Internal finance (CEO, Finance)
    **{(PRP1, h): _COM for h in ("Introduction", "Proposed Solution", "Deliverables", "Timeline",
                                 "Commercial Terms", "Assumptions")},
    (PRP1, "Confidential Note"): _FIN,
    **{(PRP2, h): _COM for h in ("Introduction", "Scope", "Deliverables", "Schedule", "Commercial Terms")},
    (PRP2, "Internal Risk Assessment"): _FIN,
    **{(PRP3, h): _COM for h in ("Introduction", "Proposed Scope", "Deliverables", "Timeline",
                                 "Commercial Terms")},
    (PRP3, "Internal Notes"): _FIN,
}

Q = [
    # ---- BRD P001
    ("q01", "What does the e-commerce business want to launch?", [(BRD1, "Background")], ["online store|order tracking"]),
    ("q02", "What are the business objectives of the E-Commerce platform?", [(BRD1, "Business Objectives")], ["abandonment"]),
    ("q03", "What is BR-02 in the E-Commerce BRD?", [(BRD1, "Requirements")], ["payment method"]),
    ("q04", "Can operations staff update order status in the e-commerce store?", [(BRD1, "Requirements"), (PRD1, "User Stories")], ["order status"]),
    ("q05", "What is the launch target for the E-Commerce platform?", [(BRD1, "Constraints"), (PRP1, "Timeline")], ["12 weeks|12-week|twelve"]),
    ("q06", "Is the first e-commerce release limited to certain countries?", [(BRD1, "Constraints")], ["one country|single country"]),
    ("q07", "Who are the stakeholders of the E-Commerce BRD?", [(BRD1, "Stakeholders")], ["sponsor"]),
    # ---- PRD P001
    ("q08", "What is in scope for the E-Commerce product?", [(PRD1, "Scope")], ["checkout", "order tracking|tracking"]),
    ("q09", "What does user story US-02 say in the E-Commerce PRD?", [(PRD1, "User Stories")], ["pay securely|securely"]),
    ("q10", "When is an e-commerce payment confirmation recorded?", [(PRD1, "Acceptance Criteria")], ["provider confirmation|provider confirms|confirmation from the provider"]),
    ("q11", "Are e-commerce operations status changes logged?", [(PRD1, "Acceptance Criteria"), (PRD1, "Non-Functional")], ["audit"]),
    ("q12", "What are the non-functional requirements for the E-Commerce platform?", [(PRD1, "Non-Functional")], ["HTTPS"]),
    ("q13", "Who can initiate refunds in the E-Commerce platform?", [(PRD1, "Admin-only feature")], ["operations administrator|operations admin"]),
    ("q14", "Which e-commerce user story covers searching products?", [(PRD1, "User Stories")], ["US-01"]),
    # ---- Proposal P001
    ("q15", "What solution is proposed for the E-Commerce project?", [(PRP1, "Proposed Solution")], ["storefront"]),
    ("q16", "What are the deliverables of the E-Commerce proposal?", [(PRP1, "Deliverables")], ["UX/UI|design", "payment integration"]),
    ("q17", "How is the E-Commerce timeline split into phases?", [(PRP1, "Timeline")], ["build"]),
    ("q18", "What is the total price of the E-Commerce proposal?", [(PRP1, "Commercial Terms")], ["24,000|24000|24k"]),
    ("q19", "What is the payment schedule for the E-Commerce proposal?", [(PRP1, "Commercial Terms")], ["kickoff|kick-off", "40%"]),
    ("q20", "What must the client supply for the E-Commerce project?", [(PRP1, "Assumptions")], ["product data"]),
    ("q21", "What is the internal estimated delivery cost for the E-Commerce project?", [(PRP1, "Confidential Note")], ["15,000|15000|15k"]),
    # ---- BRD P002
    ("q22", "What is the business goal of Droop LMS?", [(BRD2, "Business Goal")], ["learning platform|courses"]),
    ("q23", "Can instructors publish courses immediately in Droop LMS?", [(BRD2, "Business Requirements")], ["review"]),
    ("q24", "What does BR-04 of the Droop LMS BRD require?", [(BRD2, "Business Requirements")], ["completion"]),
    ("q25", "Who manages users and platform settings in Droop LMS?", [(BRD2, "Business Requirements")], ["admin"]),
    ("q26", "What are the success metrics for Droop LMS?", [(BRD2, "Success Metrics")], ["completion rate"]),
    ("q27", "Who are the stakeholders of Droop LMS?", [(BRD2, "Stakeholders")], ["instructors", "students"]),
    # ---- PRD P002
    ("q28", "What features does Droop LMS have?", [(PRD2, "Features")], ["quiz"]),
    ("q29", "Does Droop LMS support downloadable materials?", [(PRD2, "Features")], ["downloadable"]),
    ("q30", "Who can see quiz answer keys in Droop LMS?", [(PRD2, "Restricted Content")], ["instructor"]),
    ("q31", "Who can see student submissions in Droop LMS?", [(PRD2, "Restricted Content")], ["submitted"]),
    ("q32", "What does user story US-03 say in the Droop LMS PRD?", [(PRD2, "User Stories")], ["correct answers|quizzes"]),
    ("q33", "How are Droop LMS answer-key endpoints protected?", [(PRD2, "Acceptance Criteria")], ["server-side|server side"]),
    ("q34", "Is course access checked on every request in Droop LMS?", [(PRD2, "Acceptance Criteria")], ["every request"]),
    # ---- Proposal P002
    ("q35", "What is in scope of the Droop LMS proposal?", [(PRP2, "Scope"), (PRP2, "Deliverables")], ["instructor portal"]),
    ("q36", "What are the Droop LMS proposal deliverables?", [(PRP2, "Deliverables")], ["handover"]),
    ("q37", "How long is the Droop LMS schedule?", [(PRP2, "Schedule")], ["14 weeks|14-week|fourteen"]),
    ("q38", "What is the illustrative total for the Droop LMS proposal?", [(PRP2, "Commercial Terms")], ["38,000|38000|38k"]),
    ("q39", "How are Droop LMS payments structured?", [(PRP2, "Commercial Terms")], ["milestone"]),
    ("q40", "What is the internal contingency reserve for Droop LMS?", [(PRP2, "Internal Risk Assessment")], ["4,000|4000|4k"]),
    ("q41", "What risks could affect the Droop LMS schedule?", [(PRP2, "Internal Risk Assessment")], ["video hosting|migration"]),
    # ---- BRD P003
    ("q42", "What is the business goal of Hub Drives?", [(BRD3, "Business Goal")], ["rent"]),
    ("q43", "How can guests search vehicles in Hub Drives?", [(BRD3, "Business Requirements"), (PRD3, "User Stories"), (PRD3, "Features")], ["location"]),
    ("q44", "What does BR-04 say in the Hub Drives BRD?", [(BRD3, "Business Requirements")], ["dispute"]),
    ("q45", "Who are the Hub Drives stakeholders?", [(BRD3, "Stakeholders")], ["providers", "support"]),
    ("q46", "What are the Hub Drives success metrics?", [(BRD3, "Success Metrics")], ["cancellation rate"]),
    # ---- PRD P003
    ("q47", "What features are in Hub Drives?", [(PRD3, "Features")], ["calendar"]),
    ("q48", "When is the provider phone number shown to the guest in Hub Drives?", [(PRD3, "Access Rules"), (PRD3, "Acceptance Criteria")], ["confirm"]),
    ("q49", "Who can see admin dispute notes in Hub Drives?", [(PRD3, "Access Rules")], ["operations staff|operations"]),
    ("q50", "Who can configure commission in Hub Drives?", [(PRD3, "Access Rules")], ["finance"]),
    ("q51", "What does user story US-02 say in the Hub Drives PRD?", [(PRD3, "User Stories")], ["availability"]),
    ("q52", "Are Hub Drives dispute notes included in guest-facing API responses?", [(PRD3, "Acceptance Criteria")], ["not included|no"]),
    # ---- Proposal P003
    ("q53", "What is the proposed scope for Hub Drives?", [(PRP3, "Proposed Scope")], ["provider portal"]),
    ("q54", "What are the Hub Drives proposal deliverables?", [(PRP3, "Deliverables"), (PRP3, "Proposed Scope")], ["operations dashboard"]),
    ("q55", "How long is the Hub Drives timeline?", [(PRP3, "Timeline")], ["16 weeks|16-week|sixteen"]),
    ("q56", "What is the illustrative total for the Hub Drives proposal?", [(PRP3, "Commercial Terms")], ["46,000|46000|46k"]),
    ("q57", "What is the gross margin target for Hub Drives?", [(PRP3, "Internal Notes")], ["32%|32 percent"]),
    ("q58", "What risk items are listed for the Hub Drives proposal?", [(PRP3, "Internal Notes")], ["fraud"]),
    # ---- cross-section
    ("q59", "Which E-Commerce user story matches business requirement BR-03?", [(PRD1, "User Stories"), (BRD1, "Requirements")], ["US-03"]),
    # ---- not in the corpus
    ("q60", "What database does Droop LMS use?", [], []),
    ("q61", "What is the Hub Drives refund policy for guests?", [], []),
    ("q62", "Who is the CEO of the E-Commerce client company?", [], []),
]

# Eval users: CEO + one user per (project, role) for the 5 project roles that exist today.
ROLES = ("pm", "developer", "qa", "finance", "client")
USERS = {"u-ceo": ("ceo", None)} | {f"u-{p.lower()}-{r}": (r, p) for p in ("P001", "P002", "P003") for r in ROLES}


def target_readers(doc_id: str, heading: str) -> set[str]:
    """Readers under the target policy; moved price lines inherit their source section's readers."""
    if heading.startswith("Commercial details — from "):
        heading = heading.removeprefix("Commercial details — from ")
    return SECTION_READERS.get((doc_id, heading), {"ceo", "pm"})   # unknown → fail-closed default


def allowed(user: str, doc_id: str, heading: str) -> bool:
    role, project = USERS[user]
    if role != "ceo" and PROJECT[doc_id] != project:
        return False
    return role in target_readers(doc_id, heading)
