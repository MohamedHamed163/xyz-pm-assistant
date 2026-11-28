# W-13 — How do sample project IDs and heading vocabulary map onto ours?

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-28

The samples use P001 E-Commerce / P002 Droop LMS / P003 Hub Drives; the dev DB has P001 Droob AI,
P002 Hub Drives, P003 hamo sports wear. And 35% of sample sections are unclassified because headings
differ ("Business Goal", "Features", "Success Metrics", "Proposed Solution"). Questions: separate
environment / re-numbering / ID namespacing; extend keywords vs per-template mappings.

## Answers (in progress)

- **Q1 — project identity:** the upload form's project choice always decides; the document's Project ID/name is only checked — mismatch with both the chosen project's id and name → review note, never moves the document or changes access. Sample testing: create "E-Commerce Platform" and "Droop LMS" projects, Hub Drives samples go to existing Hub Drives; no renumbering. Automated tests keep their own DB with sample IDs. *(agreed)*
- **Q2 — heading vocabulary:** extend the single keyword list (no per-template mappings): BRD Business Goal / Success Metrics → goals · PRD Features / Non-Functional / Admin-only feature / Restricted Content / Access Rules → requirements · Proposal Proposed Solution → scope, Assumptions → engagement, Confidential Note / Internal Notes / Internal Risk Assessment → Internal finance. Safety rule: in proposals any heading containing "confidential" or "internal" → Internal finance; in BRD/PRD such headings stay unclassified. Applies to new uploads only (W-09). All 15 sample unclassified sections get a topic; verify in W-01 that none widens beyond the documents' declared policy. *(agreed)*

## Resolution

Project = the upload form's choice; the document's project id/name is only checked (mismatch → review note). Sample headings added to the shared keyword list, with "confidential/internal" proposal headings → Internal finance. No renumbering, no per-template lists.
