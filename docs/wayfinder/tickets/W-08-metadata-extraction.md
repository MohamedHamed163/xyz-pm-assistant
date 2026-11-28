# W-08 — Deterministic parser, LLM structured output, or both, for metadata extraction?

**Type:** research · **Mode:** AFK · **Status:** closed 2026-11-28

Measure on the 9 samples (and their PDF/DOCX renderings where the block may become a table):
1. Deterministic parse of `- **Key:** value` blocks.
2. OpenAI structured output with a JSON schema (the 14 fields from the brief), validated with Pydantic.
3. Hybrid: deterministic first, LLM only for free-text fields (Sharing Rules → restricted_sections,
   access_conditions), every LLM field marked `needs_review`.
Report per-field accuracy, ambiguity/conflict detection, cost, and how `.md` uploads should be accepted.

## Resolution

Measured in [03-metadata-extraction.md](../../audit/03-metadata-extraction.md) (40 runs, 11 fields).
**Deterministic parser is the source of truth; the LLM is a second reader whose ceiling is intersected
(stricter wins) and whose disagreements become review notes.** Parser alone: 100% on known formats but 3
leaks on unfamiliar headers; LLM alone: 93% on held-out but invents/adds roles; both with stricter-wins:
0 leaks, 4 safe over-blocks (flagged). `.md` uploads accepted with no front matter. ≈ $0.0004/upload.
