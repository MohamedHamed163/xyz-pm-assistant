"""W-01 — baseline of the CURRENT pipeline on the Nexora corpus.

    .venv/bin/python eval/retrieval/run_baseline.py              # retrieval + permissions, both embedders
    .venv/bin/python eval/retrieval/run_baseline.py --answers    # + answers with OpenAI (≈ 250 calls)

Uses a throwaway database (xyz_pm_eval). Imports app code unchanged; changes nothing in the repo.
Writes eval/retrieval/baseline_results.json. Metrics:

  relevance            recall@1/3/8 and MRR of the expected section, asked as the CEO (sees everything)
  context completeness all facts present in the passages that pass the distance threshold (CEO)
  permission (fact)    for every (user, fact): can the user retrieve it (anywhere, k=∞) vs. may they (target
                       policy) → leaks (retrievable, not allowed) and over-blocks (allowed, not retrievable)
  unauthorized rate    share of top-8 chunks per (user, question) the target policy does not allow — must be 0
  authorized recall    for allowed (user, question) pairs: expected section in the user's top-8
  answers (--answers)  CEO: fact accuracy, citation precision, not-found correctness;
                       P001 users × P001 questions: answer leaks (fact appears though not allowed)
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

from app.answer import answer_question, default_max_distance  # noqa: E402
from app.db import apply_migrations, connect  # noqa: E402
from app.embeddings import HashingEmbedder, OpenAIEmbedder  # noqa: E402
from app.ingestion import run_worker_until_empty, submit_document  # noqa: E402
from app.llm import OpenAIChatLLM  # noqa: E402
from app.retrieval import retrieve  # noqa: E402
from app.seed_db import seed_company  # noqa: E402

from dataset import PROJECT, Q, USERS, allowed  # noqa: E402

SAMPLES = Path("/Users/mohamedhamed/Downloads/Nexora_Permission_RAG_Sample_Documents")
TYPE = {"BRD": "brd", "PRD": "prd", "Proposal": "proposal"}
NAMES = {"P001": ("E-Commerce Platform", "{E-Commerce,ecommerce}"), "P002": ("Droop LMS", "{Droop}"),
         "P003": ("Hub Drives", "{Hub}")}


def hit(fact: str, text: str) -> bool:
    t = text.lower().replace("‑", "-")
    return any(alt.lower() in t for alt in fact.split("|"))


def setup(embedder) -> psycopg.Connection:
    with psycopg.connect("dbname=postgres", autocommit=True) as admin:
        admin.execute('DROP DATABASE IF EXISTS "xyz_pm_eval" WITH (FORCE)')
        admin.execute('CREATE DATABASE "xyz_pm_eval"')
    conn = connect("dbname=xyz_pm_eval")
    apply_migrations(conn)
    seed_company(conn)
    for pid, (name, aliases) in NAMES.items():
        conn.execute("""INSERT INTO projects (id, company_id, name, aliases) VALUES (%s,'xyz',%s,%s)
                        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, aliases=EXCLUDED.aliases""",
                     (pid, name, aliases))
    for uid, (role, project) in USERS.items():
        conn.execute("""INSERT INTO users (id, company_id, name, email, role) VALUES (%s,'xyz',%s,%s,%s)
                        ON CONFLICT (id) DO NOTHING""", (uid, uid, f"{uid}@eval.test", role))
        if project:
            conn.execute("INSERT INTO project_members VALUES (%s,%s) ON CONFLICT DO NOTHING", (uid, project))
    # The current Markdown path needs front matter — the best case today (see 02-evaluation.md §1).
    for p in sorted(SAMPLES.rglob("*.md")):
        if p.name == "README.md":
            continue
        text = p.read_text()
        meta = dict(re.findall(r"^- \*\*(.+?):\*\* (.+)$", text, re.M))
        title = text.splitlines()[0].lstrip("# ").strip()
        front = (f"---\nid: {meta['Document ID'].lower()}\ntitle: {json.dumps(title)}\n"
                 f"project: {meta['Project ID']}\ndoc_type: {TYPE[meta['Document Type']]}\nversion: \"1\"\n---\n")
        submit_document(conn, front + text, uploaded_by="u-mona")
    results = run_worker_until_empty(conn, embedder)
    assert all(r.outcome == "ready" for r in results), [(r.document_id, r.outcome) for r in results]
    return conn


def heading_of(chunk) -> tuple[str, str]:
    return chunk.document_id, chunk.heading


def retrieval_metrics(conn, embedder) -> dict:
    max_d = default_max_distance(embedder)
    answerable = [q for q in Q if q[2]]
    ranks, complete, top = [], 0, {}
    for qid, text, sections, facts in answerable:
        chunks = retrieve(conn, "u-ceo", text, embedder, k=8, audit=False).chunks
        top[qid] = chunks
        pos = next((i + 1 for i, c in enumerate(chunks) if _matches(c, sections)), None)
        ranks.append(pos)
        passages = " ".join(c.content for c in chunks if c.distance <= max_d)
        complete += all(hit(f, passages) for f in facts)
    n = len(answerable)
    rel = {f"recall@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 8)}
    rel["mrr"] = round(sum(1 / r for r in ranks if r) / n, 3)
    rel["context_completeness"] = round(complete / n, 3)
    rel["missed_at_8"] = [q[0] for q, r in zip(answerable, ranks) if not r]

    # Permissions: everything each user can retrieve (k = all) against the target policy.
    leaks, over, checked = [], [], 0
    visible = {u: retrieve(conn, u, "everything", embedder, k=10_000, audit=False).chunks for u in USERS}
    for qid, text, sections, facts in answerable:
        may_any = {u: any(allowed(u, d, h) for d, h in sections) for u in USERS}
        for u, chunks in visible.items():
            docs = {d for d, _ in sections}       # the fact must come from an expected document
            with_fact = [c for c in chunks if c.document_id in docs and all(hit(f, c.content) for f in facts)]
            can = all(any(hit(f, c.content) for c in chunks if c.document_id in docs) for f in facts)
            checked += 1
            # leak = the user retrieves the fact from a section the target policy doesn't let them read
            if any(not allowed(u, c.document_id, c.heading) for c in with_fact):
                leaks.append((u, qid))
            if may_any[u] and not can:
                over.append((u, qid))

    # Unauthorized share of top-8 + authorized recall, per (user, question).
    bad = tot = 0
    auth_hits = auth_n = 0
    bad_examples = []
    for u in USERS:
        for qid, text, sections, facts in Q:
            chunks = retrieve(conn, u, text, embedder, k=8, audit=False).chunks
            for c in chunks:
                tot += 1
                if not allowed(u, c.document_id, c.heading):
                    bad += 1
                    if len(bad_examples) < 15:
                        bad_examples.append((u, qid, c.document_id, c.heading))
            if sections and any(allowed(u, d, h) for d, h in sections):
                auth_n += 1
                auth_hits += any(_matches(c, sections) and allowed(u, c.document_id, c.heading) for c in chunks)
    perm = dict(fact_checks=checked, leaks=len(leaks), leak_list=leaks, over_blocks=len(over),
                over_block_rate=round(len(over) / max(1, sum(
                    1 for q in answerable for u in USERS if any(allowed(u, d, h) for d, h in q[2]))), 3),
                unauthorized_rate_top8=round(bad / max(1, tot), 4), unauthorized_chunks=bad, chunks_seen=tot,
                unauthorized_examples=bad_examples, authorized_recall_at8=round(auth_hits / max(1, auth_n), 3))
    return dict(relevance=rel, permissions=perm)


def _matches(chunk, sections) -> bool:
    d, h = chunk.document_id, chunk.heading.removeprefix("Commercial details — from ")
    return (d, h) in set(sections)


def answer_metrics(conn, embedder) -> dict:
    llm = OpenAIChatLLM()
    ceo = dict(correct=0, answerable=0, notfound_ok=0, unanswerable=0, cited=0, cited_ok=0, wrong=[])
    for qid, text, sections, facts in Q:
        a = answer_question(conn, "u-ceo", text, embedder=embedder, llm=llm)
        if not sections:
            ceo["unanswerable"] += 1
            ok = a.outcome != "answered"
            ceo["notfound_ok"] += ok
            if not ok:
                ceo["wrong"].append((qid, "answered an unanswerable question", a.text[:120]))
            continue
        ceo["answerable"] += 1
        good = a.outcome == "answered" and all(hit(f, a.text) for f in facts)
        ceo["correct"] += good
        if not good:
            ceo["wrong"].append((qid, a.outcome, a.text[:160]))
        for c in a.citations:
            ceo["cited"] += 1
            ceo["cited_ok"] += (c.document_id, c.heading.removeprefix("Commercial details — from ")) in set(sections)
    ceo_out = dict(answer_accuracy=round(ceo["correct"] / ceo["answerable"], 3),
                   not_found_correct=f'{ceo["notfound_ok"]}/{ceo["unanswerable"]}',
                   citation_precision=round(ceo["cited_ok"] / max(1, ceo["cited"]), 3), wrong=ceo["wrong"])

    # Answer-level leaks: P001 users on P001 questions they may NOT read (and correct answers where they may).
    p001_users = [u for u, (r, p) in USERS.items() if p == "P001"]
    leaks, denied_ok, pairs_denied, allowed_ok, pairs_allowed = [], 0, 0, 0, 0
    for qid, text, sections, facts in Q:
        if not sections or PROJECT[sections[0][0]] != "P001":
            continue
        for u in p001_users:
            may = any(allowed(u, d, h) for d, h in sections)
            a = answer_question(conn, u, text, embedder=embedder, llm=llm)
            got = a.outcome == "answered" and all(hit(f, a.text) for f in facts)
            if may:
                pairs_allowed += 1
                allowed_ok += got
            else:
                pairs_denied += 1
                if got:
                    leaks.append((u, qid, a.text[:120]))
                else:
                    denied_ok += 1
    return dict(ceo=ceo_out, p001=dict(denied_pairs=pairs_denied, answer_leaks=len(leaks), leak_list=leaks,
                                       allowed_pairs=pairs_allowed,
                                       allowed_answered_correctly=round(allowed_ok / max(1, pairs_allowed), 3)))


def main():
    out = {"questions": len(Q), "answerable": sum(1 for q in Q if q[2]), "users": len(USERS)}
    for name, emb in (("offline-hashing", HashingEmbedder()), ("openai-3-small", OpenAIEmbedder())):
        t0 = time.time()
        conn = setup(emb)
        out[name] = retrieval_metrics(conn, emb)
        if name.startswith("openai") and "--answers" in sys.argv:
            out[name]["answers"] = answer_metrics(conn, emb)
        out[name]["seconds"] = round(time.time() - t0, 1)
        conn.close()
        print(name, json.dumps({k: v for k, v in out[name].items()}, default=str)[:1500], "\n")
    (HERE / "baseline_results.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
