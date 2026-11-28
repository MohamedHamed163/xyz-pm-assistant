# W-05 — How do we separate client-facing pricing from internal cost/margin? (fixes V1)

**Type:** grilling · **Mode:** HITL · **Status:** closed 2026-11-26 · **Severity:** High

## Evidence
"Internal estimated delivery cost: USD 15,000" sat in an internal "Confidential Note" (unclassified →
CEO/PM). The price splitter moved it into `commercial`, which **Client and Finance** read: restricted
content inherited a broader permission. "Gross margin target: 32%" and "contingency reserve" weren't
detected at all.

## Questions
- Two topics — `commercial_client` (price, payment terms) and `commercial_internal` (cost, margin,
  reserves, subcontractor rates) — or a sensitivity flag?
- Rule: a moved line may only go to a topic **at least as restricted** as its source section?
- Detection: which non-currency signals (margin %, reserve, contingency, "internal", "not client-facing")?

## Resolution (2026-11-26, grilled with the user)

1. **Two topics replace `commercial`** in all three document types:
   - **Pricing** — what the client is offered/pays (totals, per-plan prices, payment terms, invoices).
     Readers: CEO, PM, Finance, Client (own project).
   - **Internal finance** — what XYZ keeps internal (delivery cost, margin, markup, contingency/reserve,
     subcontractor rates, negotiation notes). Readers: **CEO, Finance**. PMs excluded by default; the
     (No per-document grants — simplified W-02/W-03; change the role table to give PMs Internal finance.)
   - Developer and QA read neither.
2. **Safety rule for moved lines:** a line may only move into a topic whose readers are a **subset of
   its source section's readers**. If none qualifies, it stays where it is and the section is flagged
   ("contains a price — check who should see it"). Moving text can never widen access.
3. **Detection (deterministic, testable):**
   - Money line = currency amount **or** a number/percentage next to margin, markup, profit,
     commission, contingency — plus a money word.
   - Internal markers (internal, cost estimate, delivery cost, margin, markup, profit, contingency,
     reserve, subcontractor, rate card, walk-away, not client-facing, not for client distribution)
     → Internal finance; otherwise Pricing; **unsure → Internal finance**.
   - Headings: Confidential Note / Internal Notes / Internal Risk Assessment / Internal Cost →
     Internal finance; Commercial Terms / Pricing / Payment Terms → Pricing.
   - Every detected or moved money line is listed on the review screen. AI-based sensitivity detection
     is deferred to W-08.
4. **Migration:** existing `commercial` sections are re-checked with rule 3 — client-facing → Pricing
   (no change for anyone); internal or unsure → Internal finance (access only removed) and listed for
   review. The old topic is removed afterwards. Design §12's Commercial rule is superseded; new tests:
   Client and PM must not retrieve "USD 15,000", "32%", "USD 4,000"; Finance can.
