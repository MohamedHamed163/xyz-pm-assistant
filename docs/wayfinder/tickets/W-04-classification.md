# W-04 — What does a classification level do?

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-26

Levels seen: Internal, Confidential, Commercial-Confidential. Question: is classification a
**document-level ceiling** (e.g. Commercial-Confidential → only CEO/PM/Finance/Legal, regardless of
topics), a default for sections, or display-only? How does it combine with topic access, and can a
section be more restricted than its document (yes — "Confidential Note") but never less?

## Answers (in progress)

- **Q1 — what a level does:** always shown (UI, citations). It acts as a whole-document ceiling **only when the document has no "Authorized Roles" list**; when both exist, the stricter wins. It only narrows access for that document and never changes roles. *(agreed)*
- **Q2 — ceiling per level (fallback, used only without Authorized Roles):** Internal = CEO, PM, Developer, QA, Finance, Legal, Operations (no Client) · Confidential = CEO, PM, Developer, QA · Commercial-Confidential = CEO, PM, Finance, Legal. Only a ceiling; the role table still decides topics inside it. Client access to such documents only via an explicit Authorized Roles list that names Client (no grants — simplified W-03). *(agreed)*
- **Q3 — missing / unknown level:** missing → no extra ceiling, review note, publish not blocked · unknown or misspelled → treated as Commercial-Confidential + flagged until a CEO/PM confirms a level; never fuzzy-matched · case, whitespace and dash variants normalised. *(agreed)*
- **Q4 — sections vs document:** a section may be **narrower** than its document (auto from clear heading/wording cues per W-05, or by CEO/PM hand — persisted per W-09), **never wider**. The only route to wider (e.g. client sees part of an Internal doc) is a CEO-approved extract, decided in W-07. *(agreed)*

## Resolution

Effective access to a section = **document ceiling** (Authorized Roles; else classification fallback; stricter wins when both) **∩ role table** (role × doc type × topic) **∩ section restriction**. Classification is always displayed; fallback ceilings: Internal (all staff, no Client), Confidential (CEO, PM, Dev, QA), Commercial-Confidential (CEO, PM, Finance, Legal). Missing level → no ceiling + note; unknown level → strictest + flag until confirmed. Sections only narrow; never wider (W-07 dropped extracts). Roles unchanged.
