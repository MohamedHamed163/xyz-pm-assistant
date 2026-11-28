"""W-08 — compare metadata extraction approaches on the Nexora samples.

    ../.venv/bin/python eval/metadata/run_w08.py            # deterministic only (offline)
    ../.venv/bin/python eval/metadata/run_w08.py --llm      # + OpenAI structured output and hybrid

Three renderings of each label block are tested, because uploads arrive as PDF/DOCX:
  markdown — the original `- **Key:** value` lines
  plain    — `Key: value` lines (what PDF text extraction typically yields)
  table    — `| Key | Value |` rows (what our PDF/DOCX parser makes of a 2-column table)
Writes eval/metadata/w08_results.json. Not production code.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend"))
import app  # noqa: E402,F401  (loads .env without printing anything)
import os  # noqa: E402

from ground_truth import HELDOUT, PERTURBED, SAMPLES, TRUTH  # noqa: E402

FIELDS = ["document_id", "project_id", "project_name", "document_type", "classification", "owner",
          "authorized_roles", "unknown_roles", "has_role_qualifier", "restricts_money", "needs_review_note"]


# ---------------------------------------------------------------- corpus
def load_cases() -> dict[str, tuple[str, dict]]:
    texts = {}
    for p in sorted(Path(SAMPLES).rglob("*.md")):
        if p.name == "README.md":
            continue
        t = p.read_text()
        doc_id = re.search(r"Document ID:\*\* (\S+)", t).group(1)
        texts[doc_id] = t
    cases = {d: (t, dict(TRUTH[d], document_id=d)) for d, t in texts.items()}
    for name, (src, fn, over) in PERTURBED.items():
        cases[name] = (fn(texts[src]), dict(TRUTH[src], document_id=src, **over))
    cases.update(HELDOUT)
    return cases


def render(text: str, style: str) -> str:
    if style == "markdown":
        return text
    out = []
    for line in text.splitlines():
        m = re.match(r"^- \*\*(.+?):\*\* (.+)$", line)
        if not m:
            out.append(line)
        elif style == "plain":
            out.append(f"{m.group(1)}: {m.group(2)}")
        else:
            if not out or not out[-1].startswith("|"):
                out += ["| Field | Value |", "| --- | --- |"]
            out.append(f"| {m.group(1)} | {m.group(2)} |")
    return "\n".join(out)


# ---------------------------------------------------------------- 1. deterministic
ROLE_WORDS = {"ceo": "ceo", "chief executive": "ceo", "project manager": "pm", "pm": "pm",
              "developer": "developer", "developers": "developer", "engineering": "developer",
              "qa": "qa", "quality assurance": "qa", "finance": "finance", "financial manager": "finance",
              "legal": "legal", "operations": "operations", "client": "client", "clients": "client"}
CLASSES = {"internal", "confidential", "commercial_confidential", "public"}
_KV = re.compile(r"^\s*(?:[-*•]\s*)?(?:\|\s*)?\**([A-Za-z][A-Za-z ]{1,30}?)\**\s*(?::\**|\|)\s*(.+?)\s*\|?\s*$")
_MONEY = re.compile(r"\b(pricing|price|prices|cost|costs|margin|margins|rates|economics|financial|reserve|budget)\b", re.I)
_RESTRICT = re.compile(r"\b(restricted|do not share|must not|not receive|outside|only)\b", re.I)
_NOTE = re.compile(r"\b(team|student|students|guest|vendor|instructor|approval|extracts?|excerpts?|technical|analytics|"
                   r"admin|fraud|contact|dispute|commission|public)\b", re.I)


def _norm_role(item: str) -> tuple[str | None, str | None]:
    s = item.strip().lower()
    for word in sorted(ROLE_WORDS, key=len, reverse=True):
        if re.match(rf"{re.escape(word)}\b", s):
            return ROLE_WORDS[word], None
    head = re.findall(r"[a-z]+", s)
    return None, (head[0].rstrip("s") if head else None)


def deterministic(text: str) -> dict:
    kv = {}
    for line in text.splitlines()[:40]:
        if line.startswith("#"):
            continue
        m = _KV.match(line)
        if m and m.group(1).strip().lower() not in ("field",) and not set(m.group(2)) <= set("-| "):
            kv.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    out: dict = {"document_id": kv.get("document id"), "project_id": kv.get("project id"),
                 "project_name": kv.get("project"), "owner": kv.get("document owner")}
    dt = (kv.get("document type") or (out["document_id"] or "").split("-")[0]).lower()
    out["document_type"] = dt if dt in ("brd", "prd", "proposal") else None
    raw = kv.get("classification")
    if raw is None:
        out["classification"] = "missing"
    else:
        c = re.sub(r"[\s\-–—]+", "_", raw.strip().lower())
        out["classification"] = c if c in CLASSES else "unknown"
    roles_raw = kv.get("authorized roles")
    if roles_raw is None:
        out.update(authorized_roles=None, unknown_roles=set(), has_role_qualifier=False)
    else:
        main, _, qual = roles_raw.partition(";")
        known, unknown = set(), set()
        for item in main.split(","):
            k, u = _norm_role(item)
            known |= {k} if k else set()
            unknown |= {u} if u else set()
        for w in re.findall(r"[A-Za-z]+", qual):
            k, u = _norm_role(w)
            if k is None and w.lower().rstrip("s") in ("instructor", "vendor", "student", "guest"):
                unknown.add(w.lower().rstrip("s"))
        out.update(authorized_roles=known, unknown_roles=unknown, has_role_qualifier=bool(qual.strip()))
    sharing = kv.get("sharing rules", "")
    sentences = [s for s in re.split(r"(?<=[.;])\s+", sharing) if s.strip()]
    out["restricts_money"] = any(_MONEY.search(s) and _RESTRICT.search(s) for s in sentences)
    out["needs_review_note"] = any(_NOTE.search(s) or not (_MONEY.search(s) and _RESTRICT.search(s))
                                   for s in sentences)
    return out


# ---------------------------------------------------------------- 2. LLM structured output
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": FIELDS + ["review_notes"],
    "properties": {
        "document_id": {"type": ["string", "null"]}, "project_id": {"type": ["string", "null"]},
        "project_name": {"type": ["string", "null"]},
        "document_type": {"type": ["string", "null"], "enum": ["brd", "prd", "proposal", None]},
        "classification": {"type": "string",
                           "enum": ["internal", "confidential", "commercial_confidential", "public", "unknown", "missing"]},
        "owner": {"type": ["string", "null"]},
        "authorized_roles": {"type": ["array", "null"], "items": {"type": "string", "enum":
                             ["ceo", "pm", "developer", "qa", "finance", "legal", "operations", "client"]}},
        "unknown_roles": {"type": "array", "items": {"type": "string"}},
        "has_role_qualifier": {"type": "boolean"}, "restricts_money": {"type": "boolean"},
        "needs_review_note": {"type": "boolean"}, "review_notes": {"type": "array", "items": {"type": "string"}},
    },
}
PROMPT = """You extract access metadata from the header of a company document. Extract; never decide access.
Rules:
- Copy document_id, project_id, project_name, owner exactly as written; null if absent.
- classification: normalise case/spaces/dashes to internal | confidential | commercial_confidential | public.
  If the line is absent → "missing". If present but not exactly one of those (including misspellings) → "unknown".
- authorized_roles: ONLY roles listed in the "Authorized Roles" field before any ';', mapped to this vocabulary:
  ceo, pm (Project Manager), developer, qa, finance, legal, operations, client. null if the field is absent.
  Roles that don't map (e.g. Instructor, Vendor, Student) go to unknown_roles as a lowercase singular noun —
  also when they appear in a qualifier after ';'.
- has_role_qualifier: true if the Authorized Roles field has a ';' qualifier (e.g. "client receives summary only").
- restricts_money: true if Sharing Rules restrict pricing, cost, margin, rates, financial or economic information.
- needs_review_note: true if any part of Sharing Rules cannot be expressed purely as "these roles may read this
  topic" with our vocabulary (mentions teams, students, guests, vendors, approvals, extracts, technical details…).
- review_notes: short quotes of the parts that need a human."""


def llm_extract(text: str, model: str = "gpt-4.1-mini") -> tuple[dict, dict]:
    header = "\n".join(text.splitlines()[:15])
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": header}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "doc_meta", "strict": True, "schema": SCHEMA}}}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    out = json.loads(payload["choices"][0]["message"]["content"])
    for k in ("authorized_roles", "unknown_roles"):
        if out.get(k) is not None:
            out[k] = set(out[k])
    return out, payload.get("usage", {})


def hybrid(det: dict, llm: dict) -> dict:
    """Deterministic for every structured field; LLM only for the free-text Sharing Rules judgements."""
    return dict(det, restricts_money=llm["restricts_money"], needs_review_note=llm["needs_review_note"])


# ---------------------------------------------------------------- what matters: the access ceiling (W-04)
ALL = frozenset({"ceo", "pm", "developer", "qa", "finance", "legal", "operations", "client"})
LEVEL = {"internal": ALL - {"client"}, "confidential": frozenset({"ceo", "pm", "developer", "qa"}),
         "commercial_confidential": frozenset({"ceo", "pm", "finance", "legal"}), "public": ALL}
LEVEL["unknown"] = LEVEL["commercial_confidential"]           # W-04 Q3: unknown → strictest


def ceiling(meta: dict) -> frozenset:
    c = ALL
    if meta.get("authorized_roles") is not None:
        c &= frozenset(meta["authorized_roles"])
    if meta.get("classification") in LEVEL:
        c &= LEVEL[meta["classification"]]
    return c


# ---------------------------------------------------------------- scoring
def same(field, got, want) -> bool | None:
    if want is None and field == "restricts_money":
        return None
    if isinstance(want, str) and isinstance(got, str):
        return got.strip().lower() == want.strip().lower()
    return got == want


def main():
    use_llm = "--llm" in sys.argv
    cases = load_cases()
    methods = ["deterministic"] + (["llm", "hybrid"] if use_llm else [])
    score = {m: {s: {f: [0, 0] for f in FIELDS} for s in ("markdown", "plain", "table", "heldout")} for m in methods}
    ceilings, truth_ceiling = {}, {}
    misses, usage, timing = [], {"prompt_tokens": 0, "completion_tokens": 0}, {m: 0.0 for m in methods}
    for name, (text, want) in cases.items():
        for style in (("markdown", "plain", "table") if not name.startswith("H") else ("heldout",)):
            t = render(text, style) if style != "heldout" else text
            got = {}
            t0 = time.perf_counter(); got["deterministic"] = deterministic(t); timing["deterministic"] += time.perf_counter() - t0
            if use_llm:
                t0 = time.perf_counter(); got["llm"], u = llm_extract(t); timing["llm"] += time.perf_counter() - t0
                for k in usage:
                    usage[k] += u.get(k, 0)
                got["hybrid"] = hybrid(got["deterministic"], got["llm"])
            for m in methods:
                ceilings.setdefault(m, []).append((name, style, ceiling(got[m])))
            if use_llm:
                ceilings.setdefault("stricter-of-both", []).append(
                    (name, style, ceiling(got["deterministic"]) & ceiling(got["llm"])))
            truth_ceiling[(name, style)] = ceiling(want)
            for m in methods:
                for f in FIELDS:
                    ok = same(f, got[m].get(f), want[f])
                    if ok is None:
                        continue
                    score[m][style][f][1] += 1
                    score[m][style][f][0] += ok
                    if not ok:
                        misses.append(dict(case=name, style=style, method=m, field=f,
                                           got=sorted(got[m].get(f)) if isinstance(got[m].get(f), set) else got[m].get(f),
                                           want=sorted(want[f]) if isinstance(want[f], set) else want[f]))
    summary = {m: {s: {f: f"{a}/{n}" for f, (a, n) in fs.items()} for s, fs in ss.items()} for m, ss in score.items()}
    overall = {m: sum(a for ss in score[m].values() for a, n in ss.values()) /
               sum(n for ss in score[m].values() for a, n in ss.values()) for m in methods}
    # gpt-4.1-mini list price per 1M tokens: $0.40 in / $1.60 out
    cost = usage["prompt_tokens"] * 0.4e-6 + usage["completion_tokens"] * 1.6e-6
    access = {}
    for m, rows in ceilings.items():
        leaks = [(n, st, sorted(c - truth_ceiling[(n, st)])) for n, st, c in rows if c - truth_ceiling[(n, st)]]
        over = [(n, st, sorted(truth_ceiling[(n, st)] - c)) for n, st, c in rows if truth_ceiling[(n, st)] - c]
        access[m] = dict(runs=len(rows), exact=len(rows) - len({(a, b) for a, b, _ in leaks + over}),
                         wider_than_label=leaks, narrower_than_label=over)
    print(json.dumps({m: dict(runs=v["runs"], exact=v["exact"], wider=len(v["wider_than_label"]),
                              narrower=len(v["narrower_than_label"])) for m, v in access.items()}, indent=1))
    for m, v in access.items():
        print(m, "WIDER:", v["wider_than_label"], "NARROWER:", v["narrower_than_label"])
    result = dict(access_ceiling=access, cases=len(cases), renderings=3, overall_accuracy=overall, per_field=summary, misses=misses,
                  llm_usage=usage, llm_cost_usd=round(cost, 4), seconds=timing)
    (HERE / "w08_results.json").write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({"overall": overall, "cost": result["llm_cost_usd"], "seconds": timing,
                      "misses": len(misses)}, indent=1))
    for m in misses:
        print(m)


if __name__ == "__main__":
    main()
