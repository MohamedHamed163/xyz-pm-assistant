# Testing guide — XYZ PM Assistant

**App:** http://localhost:5173 (API on http://localhost:8000)

## Demo users

All users are fictional. They share one demo password, set by `DEMO_PASSWORD` in `.env`
(default below). On the login page you can also just click a user card — no typing needed.

| Name | Email | Password | Role | Projects | Can upload |
|------|-------|----------|------|----------|------------|
| Mona | mona@xyz.test | xyz-demo-2026 | CEO | All | ✅ any type, any project |
| Hamed | hamed@xyz.test | xyz-demo-2026 | Project Manager | P001 | ✅ BRD/PRD/technical/QA/minutes in P001 |
| Sara | sara@xyz.test | xyz-demo-2026 | Developer | P001 | — |
| Omar | omar@xyz.test | xyz-demo-2026 | QA Engineer | P001 | — |
| Youssef | youssef@xyz.test | xyz-demo-2026 | Developer | P002 | — |
| Amina | amina@nileretail.test | xyz-demo-2026 | Client (Nile Retail Group) | P001 | — |
| Khaled | khaled@xyz.test | xyz-demo-2026 | Finance | — (grants only) | — |

Who sees which section level:
🟢 **Client** — team, CEO and the client · 🔵 **Team** — PM, developers, QA, CEO · 🔴 **Management** — PM and CEO only.

---

## Test 1 — `P001 Payment Integration Design.pdf` (upload as **Hamed**)

Documents → Upload → New document · Project **P001** · Type **Technical Documentation**.

Set levels on review:

| Section | Level |
|---------|-------|
| 1. Overview | 🔵 Team |
| 2. Payment Flow | 🔵 Team |
| 3. Refund and Chargeback Rules | 🟢 Client |
| 4. Security Controls | 🔵 Team |
| 5. Vendor Pricing and Negotiation | 🔴 Management |

> Note: Technical documents are not readable by clients by role, so even the 🟢 section stays hidden
> from Amina. That's expected — try Test 2 for client sharing.

| Ask as | Question | Expected |
|--------|----------|----------|
| Sara | How are Paymob webhooks verified? | HMAC-SHA512, rejected if older than 5 min |
| Sara | What card fee did we negotiate with Paymob? | "I couldn't find…" (management) |
| Hamed | What card fee did we negotiate with Paymob, and what margin do we keep? | 2.25% + EGP 1.50; 0.5% margin |
| Amina | How long do refunds take? | Neutral — clients can't read technical docs |

## Test 2 — `P001 UAT Plan.docx` (upload as **Hamed**)

New document · Project **P001** · Type **Meeting Minutes & Sprint Reports**.
(Clients can read 🟢 sections of BRDs, PRDs and minutes, but never QA or technical documents —
if you pick "QA & Testing" here, Amina won't see anything from it, whatever the levels say.)

| Section | Level |
|---------|-------|
| Introduction | 🟢 Client |
| 1. UAT Schedule | 🟢 Client |
| 2. Client Responsibilities | 🟢 Client |
| 3. Test Scope and Entry Criteria | 🔵 Team |
| 4. Known Issues Going Into UAT | 🔵 Team |
| 5. QA Staffing and Cost | 🔴 Management |

The publish confirmation should say **"3 sections will be visible to the client (Nile Retail Group)"**.

| Ask as | Question | Expected |
|--------|----------|----------|
| Amina | When is UAT week 2 and what does it cover? | 2027-01-11 to 01-15, checkout and payments |
| Amina | How many testers does NRG need to provide? | 4 store operations + 1 finance |
| Amina | What known issues are going into UAT? | Neutral (team) |
| Omar | What known issues are going into UAT? | BUG-418, BUG-421, Odoo sync lag |
| Omar | How much are the contract QA engineers costing? | Neutral (management) |
| Hamed | How much are the contract QA engineers costing? | USD 2,800/month each + USD 4,000 overtime |

## Test 3 — `P002 Droop Sprint 4 Review.pdf` (upload as **Mona**)

Hamed can't upload to P002 — try it to see the project list only offers P001. As **Mona**:
New document · Project **P002** · Type **Meeting Minutes & Sprint Reports**.

| Section | Level |
|---------|-------|
| 1. Sprint Summary | 🟢 Client |
| 2. SSO Pilot Status | 🟢 Client |
| 3. Technical Issues | 🔵 Team |
| 4. Commercial Risk | 🔴 Management |

| Ask as | Question | Expected |
|--------|----------|----------|
| Youssef | Why did the SAML metadata refresh fail? | University rotated its certificate; now polled every 6 hours |
| Youssef | Are we planning a price increase for Delta Academy? | Neutral (management) |
| Mona | Are we planning a price increase for Delta Academy? | 15% at the Q1 2027 renewal; USD 4,500/month overrun |
| Sara | How did the Cairo Tech University pilot go? | Neutral — Sara is not on P002 |

---

## More things to try

- **Fix a mistake live:** Documents → Live documents → open a document → move a section to
  🟢 Client → ask as Amina immediately → move it back → ask again.
- **New version:** upload the same file again with "New version of an existing document". Your
  previous levels are pre-filled; changed sections get a "New / changed" badge.
- **Restore:** after publishing a new version, use "Restore previous version" in Live documents.
- **Merge / split:** on review, merge two sections (the stricter level wins) or split one at a paragraph.
- **Bad files:** rename any image or `.zip` to `.pdf` and upload it — it's rejected by content.
- **Permissions:** sign in as Sara or Amina — there is no Documents button.
