# W-03 — Which roles, users and groups exist, and which are external?

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-26

The samples name Finance, Legal, Operations, Account Director / account team, Instructor, Vendor,
Student, "client contacts listed in CRM", "named proposal team". Today: ceo, pm, developer, qa,
finance, client — no users/groups on documents.

Questions: which become roles vs groups vs per-user grants? Which are external (never see internal
content by default)? Are roles global or per project? Do per-user document grants come back (removed in
migration 007)?

## Resolution (2026-11-26, grilled with the user)

1. **Roles.** The existing six roles (CEO, PM, Developer, QA, Finance, Client) stay **exactly as they
   are** — names and rules unchanged (apart from W-05's Pricing / Internal finance split).
   **Two internal roles are added:** **Legal** (Pricing, Internal finance, Engagement terms; no
   technical topics) and **Operations** (like QA: rules, requirements, delivery; no money). Exact topic
   rows are set in the rules table when built.
   - Account Director / account team → a **project group**, not a role.
   - Instructor, Vendor, Student → users of the client's product; **not roles now**; any access goes
     through client-style sharing (W-07).
   - "Client contacts listed in CRM" → **Client** users with per-person grants.
2. **Roles stay global** (one role per person; membership decides where it applies). Per-project
   roles can be added later as an override if ever needed.
3. **Groups and grants**, created only by the **CEO** (they are W-02's human approval for widening):
   - **Project groups** (e.g. "P001 Account team") receive extra topics on that project's documents,
     added to members' role access. Managed on the Team tab.
   - **Personal grants**: one user, one document or project, specific topics, optional expiry.
   - **External users (Client) can never receive Internal finance or Unclassified**, whatever a grant says.
   - All changes audited; revocation applies on the next question.
4. **Labels naming people/teams** become **one-click CEO suggestions** on review (never auto-matched;
   a name in a document is not an identity). The restricting half still applies at once — e.g. a
   proposal open to "client contacts listed in CRM" is closed to other clients until the CEO grants
   named people. With no CRM in the system, the grant list *is* the access list.

## Simplified (2026-11-26, user: "keep the RAG simple")

Replaces points 3–4 above:

- **No project groups, no personal grants, no expiry.** Access = role × project membership × document label.
- Roles: the 6 existing roles unchanged + **Legal** and **Operations** (as in point 1). "Account team"
  = whoever holds CEO/Finance/Legal on the project. Instructor/Vendor/Student are not users.
- Labels naming people or teams are **ignored** (not suggestions). If a label's role list excludes
  Client (e.g. the sample proposals), clients don't see that document; to change that, the document's
  label is changed and re-uploaded.
- Clients can never read Internal finance or Unclassified.
