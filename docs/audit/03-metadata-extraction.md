# W-08 — Metadata extraction: parser, LLM, or both?

Date: 2026-11-28 · Code: [`eval/metadata/run_w08.py`](../../eval/metadata/run_w08.py) · Labels:
[`eval/metadata/ground_truth.py`](../../eval/metadata/ground_truth.py) · Raw: `eval/metadata/w08_results.json`

## What was measured

- **Cases (40 runs):**
  - The 9 Nexora headers, each in 3 renderings: Markdown `- **Key:** value`, plain `Key: value` (typical PDF text) and a 2-column table (what our PDF/DOCX parser produces).
  - 3 deliberately broken headers: misspelled level, missing *Authorized Roles*, missing *Classification*.
  - 4 **held-out** headers written *after* the parser was built: synonyms ("Owner", "Authorised roles"), other key names in a table ("Access", "Security Classification"), an unknown level and role, and a prose header.
- **Fields (11):** document id, project id, project name, type, classification, owner, authorized roles (mapped to our role keys), unknown roles, role qualifier (`; client receives…`), "restricts money info" and "needs a review note".
- **What matters most:** the **access ceiling** each method produces (W-04: Authorized Roles ∩ classification level, unknown level → strictest). It is compared with the ceiling from the hand labels:
  - **wider** = a role would get in that the label keeps out (a leak relative to the label);
  - **narrower** = a role is kept out that the label allows (over-blocking, the safe direction).

## Results

| Method | Field accuracy, known format (9+3 × 3) | Field accuracy, held-out (4) | Ceiling exact | **Wider (leak)** | Narrower | Time / cost |
|---|---|---|---|---|---|---|
| Deterministic parser | **393/393 (100%)** ¹ | 30/44 (68%) | 37/40 | **3** | 0 | ~0 ms, free |
| LLM (gpt-4.1-mini, strict JSON schema) | 370/393 (94%) | **41/44 (93%)** | 36/40 | 0 | 4 | ~2 s/doc, ≈ $0.0004/doc |
| Hybrid (parser fields + LLM for Sharing Rules only) | 390/393 | 29/44 | 37/40 | 3 | 0 | as LLM |
| **Both, stricter ceiling wins** | — | — | 36/40 | **0** | 4 | as LLM |

¹ The parser was written while looking at the 9 samples, so 100% there is expected. The held-out row is the honest generalisation number.

### What went wrong, and how it would affect access

- **Parser, unfamiliar formats:** it misses fields under new key names ("Owner", "Authorised roles", "Access", "Security Classification", "Reference") and in prose headers. A missed field means **no ceiling**, so the role table alone applies. That is 3 cases wider than the label (e.g. the table header's Commercial-Confidential was missed, so Developers and QA would still read a proposal).
- **LLM, safety-relevant mistakes:**
  - It added **Client** to Authorized Roles from the qualifier "client receives approved summary only" (3/3 renderings). The *Internal* level ceiling removed the client again, so no leak here, but only because two layers exist.
  - With *Authorized Roles* deleted, it **invented** roles (CEO, PM) from the *Authorized Users* line (3/3), which over-blocked Developers and QA.
  - It counted student *payout* information as money (PRD-P002), listed "student" as an unknown role, and in one plain-text run treated "Project Manager" as an unknown role.
- **Both, stricter wins:** intersecting the two ceilings removed every leak. The only errors left are over-blocking (the invented-roles case and one typo run), which is the safe direction, and the review note shows them to a person.

## Recommendation

1. **Deterministic parser = source of truth** for every structured field. Widen its key vocabulary cheaply ("Owner", "Authorised/Authorized Roles", "Access", "Security Classification", "Reference", "Doc ID") and handle Markdown, plain and table renderings (all three already work).
2. **LLM = second reader, never an authority.** It runs once per upload with the strict schema above, and then:
   - effective ceiling = parser ceiling ∩ LLM ceiling (**stricter wins**), so the LLM can only ever *narrow*. This matches W-02 (labels only narrow automatically).
   - every disagreement between the two becomes a **review note** ("AI read *Commercial Confidential*; the parser found no classification — confirm"). A CEO/PM can accept or correct it, and publishing is never blocked.
   - if the LLM is unavailable (no key, timeout), the parser result is used and a note says "AI check skipped".
3. **Sharing Rules:** money restrictions are detected by both. The parser's keyword rule was right on all samples, while the LLM over-read "payout" and "internal only". Use the parser's result to act and the LLM's to add notes.
4. **Unknown roles** (Instructor, Vendor, Architect…) are listed in the note and never granted (W-03).
5. **`.md` uploads:** accept them like PDF/DOCX (UTF-8 text, same 20 MB limit, heading = `#` lines). Read the header with the parser above, with **no front matter required**. Front matter stays supported for the seed path.

**Cost:** about 400 tokens per upload (≈ $0.0004). It isn't on the question path, so chat speed is unaffected.

## Limits of this measurement

- 13 distinct headers is small. The held-out set (4) shows the trend, not a precise rate.
- Real PDF/DOCX files weren't rendered; the plain and table renderings imitate what our parser produces.
- LLM results are from one run at temperature 0; small run-to-run differences were seen (e.g. the qualifier flag in plain text only).
