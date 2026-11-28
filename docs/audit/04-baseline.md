# W-01 — Evaluation dataset and baseline of the current pipeline

Date: 2026-11-28 · Dataset: [`eval/retrieval/dataset.py`](../../eval/retrieval/dataset.py) · Harness:
[`eval/retrieval/run_baseline.py`](../../eval/retrieval/run_baseline.py) · Raw: `eval/retrieval/baseline_results.json`

## Dataset

- **62 questions** over the 9 Nexora documents:
  - 58 single-section facts (every content section of every document is covered at least once);
  - 1 cross-section question (BR-03 ↔ US-03);
  - 3 questions with **no answer** in the corpus.
- For each question: the acceptable sections and short **fact strings** the answer must contain (with alternatives, e.g. `24,000|24k`). Facts are checked by string match, so no LLM grader and the results are reproducible.
- **Target policy per section** (`SECTION_READERS`): who *should* read it under the agreed decisions (W-02…W-13), i.e. role table ∩ document ceiling ∩ section restriction, plus project membership.
- **16 users:** the CEO, plus PM, Developer, QA, Finance and Client on each of P001–P003. Legal and Operations aren't in today's system, so they can't be baselined.
- Run against the **unmodified** pipeline in a throwaway database, ingested via the Markdown path with minimal front matter (the best case today), once per embedder.

## Baseline

### Relevance and answers (asked as the CEO, who sees everything)

| Metric | Offline hashing | OpenAI `text-embedding-3-small` |
|---|---|---|
| Recall@1 | 0.746 | **0.797** |
| Recall@3 | 0.881 | **0.932** |
| Recall@8 | 0.983 | 0.983 |
| MRR | 0.831 | **0.868** |
| Context completeness (all facts within the distance threshold) | 0.966 | 0.983 |
| Answer accuracy (facts in answer, gpt-4.1-mini) | — | **0.983** (57/58) |
| Not-found questions handled correctly | — | 3/3 |
| Citation precision (cited section ∈ expected) | — | 0.873 |

The one miss (q47, "What features are in Hub Drives?") retrieved the **proposal** deliverables instead of the PRD *Features* section. Two documents describe the same thing, and the vector search picked the wrong one. That is a retrieval-precision issue for W-10/W-11.

### Permissions (against the target policy)

| Metric | Value | Target |
|---|---|---|
| **Unauthorized share of top-8 chunks** (all users × all questions) | **40.8%** (3,136 / 7,688) | **0** |
| Fact leaks: a user can retrieve a fact from a section they may not read (944 user×question checks) | **72** (client 44, developer 10, finance 7, QA 6, PM 5) | **0** |
| Answer leaks: P001 users asking about P001 facts they may not read (60 pairs) | **28** (client 18, finance 4, developer 3, QA 2, PM 1) ¹ | **0** |
| Over-blocking: allowed facts the user can't retrieve | 23 (12%) | low |
| Authorized recall@8: expected section in an allowed user's top 8 | 0.843 | ≥ CEO's 0.983 |
| Allowed P001 pairs answered correctly | 0.88 (44/50) | ≥ 0.95 |
| Cross-project leakage | **0** (no user retrieved another project's chunks) | 0 |

¹ Upper bound: a few "answer leaks" use content the user *may* read in another document. For example, QA's answer to q01 came from PRD *Scope*, which QA is allowed to read. The chunk-level rows above are exact.

### Where the leaks come from (matches the audit)

- **Client** reads BRDs, PRDs and proposals in full. The target policy gives the client nothing from these documents (Authorized Roles exclude Client; W-04/W-07).
- **Developer/QA** read proposal Scope, Deliverables and Timeline, which the Commercial-Confidential ceiling forbids (W-04).
- **Finance** reads BRD goals and PRD overview/scope; the BRD and PRD ceilings exclude Finance.
- **PM** reads the proposals' Confidential Note, Internal Risk Assessment and Internal Notes, which are Internal finance (W-05). This includes the "USD 15,000" internal cost (V1).
- **Over-blocking** comes from today's *unclassified* sections: Developer and QA can't read PRD Non-Functional, Admin-only, Features, Restricted Content and Access Rules (W-06/W-13 fix this), and Finance can't read the internal notes.

## What "better" means from here

An improvement must keep **unauthorized rate = 0, fact leaks = 0 and answer leaks = 0** (hard gates). Measured from today's numbers, it should also:

- raise authorized recall@8 from 0.843 toward the CEO's 0.983, and cut over-blocking (23);
- keep or raise Recall@1 (0.797), MRR (0.868), answer accuracy (0.983) and citation precision (0.873);
- fix q47 (wrong-document retrieval).

Rerun with `.venv/bin/python eval/retrieval/run_baseline.py --answers`: about 10 minutes and under $0.20.
