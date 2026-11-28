# W-06 — Are "Access Rules" / "Restricted Content" sections document ACLs or product requirements?

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-28

PRD-P003 "Access Rules" (provider phone shown after booking confirmation) and PRD-P002 "Restricted
Content" (answer keys visible to instructors) describe how the **product being built** must behave.
Question: should RAG treat them as restrictions on who can *read those sections*, as ordinary
requirements, or both? Conditional/state-dependent access to documents: needed at all?

## Resolution (2026-11-28, grilled with the user)

Test: **does the text talk about this document, or about the app being built?** Only the first changes access.

- PRD "Admin-only feature", "Restricted Content", "Access Rules" (and similar) are **product requirements**: tagged `requirements`, readable by whoever the role table lets read PRD requirements (Developer, QA, …). Their headings are added to the keyword list so they stop being unclassified (vocabulary in W-13).
- Proposal "Confidential Note", "Internal Notes", "Internal Risk Assessment" are **about the document** ("not for the client") → narrowed automatically to **Internal finance** (W-05).
- No conditional / state-dependent document access ("phone shown after booking" is app behaviour) — stays out of scope.
