# W-01 — What dataset and metrics define "better", and what is today's baseline?

**Type:** task · **Mode:** AFK · **Blocks:** W-10, W-11 · **Status:** closed 2026-11-28

## Why it blocks decisions
Chunking and retrieval changes (W-10, W-11) can't be chosen without a measured baseline. The brief
requires "measurable results rather than claiming improvements without evidence".

## Work (agent can do alone)
- Write ~60 questions over the 9 Nexora documents: per question the expected answer facts, the
  sections that contain them, and — for each demo role — whether the question **should** be answerable.
- Metrics: recall@k / MRR (relevance), citation precision (cited section ∈ expected), context
  completeness (all expected facts retrieved), answer accuracy (fact match, LLM-graded with a rubric),
  permission-filtering accuracy, **unauthorized retrieval rate** (must be 0).
- Run on the current pipeline (offline + OpenAI) and record the baseline in `docs/audit/03-baseline.md`.

## Resolution
Dataset (62 questions, target policy per section, 16 users) and baseline in
[04-baseline.md](../../audit/04-baseline.md). Baseline (OpenAI): Recall@1 0.797, MRR 0.868, answer accuracy
0.983, citation precision 0.873; **unauthorized top-8 share 40.8%, 72 fact leaks, 28 answer leaks**, 12%
over-blocking, authorized recall@8 0.843. Gates for every change: unauthorized = leaks = 0.
