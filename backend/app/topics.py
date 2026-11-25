"""Topics: what a section is about, and who may read it.

- ``classify(doc_type, heading)`` tags a section with a topic from its heading keywords.
  Unmatched headings become ``unclassified`` (CEO/PM only) — access is never widened by a guess.
- ``split_commercial(doc_type, sections)`` moves lines with a currency amount AND a money word out of
  non-commercial sections into a "Commercial details — from …" section tagged ``commercial``, so a
  price inside an otherwise-allowed section never reaches a role that can't see Commercial.
- ``clean_markup`` removes stray layout tags some PDF generators leave in the text.

Rules come from data/seed/company.yaml (and are seeded into the database).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

SEED_FILE = Path(__file__).resolve().parents[2] / "data" / "seed" / "company.yaml"

DETAILS, COMMERCIAL, UNCLASSIFIED = "details", "commercial", "unclassified"

_CURRENCY = re.compile(
    r"(\$\s?\d|\d[\d,.]*\s?(usd|egp|aed|eur|gbp|dollars?)\b|\b(usd|egp|aed|eur|gbp)\s?\d|[€£]\s?\d)", re.I)
_MONEY_WORD = re.compile(
    r"\b(investment|invest|cost|costs|price|prices|pricing|fee|fees|payment|payments|paid|pay|budget|"
    r"invoice|invoiced|billed|billing|margin|spend|spending|rate|rates)\b", re.I)
_STRAY_TAGS = re.compile(r"</?text\b[^>]*>", re.I)
_NUMBERING = re.compile(r"^\s*(\d+(\.\d+)*\.?|[A-Z]\.|[IVX]+\.)\s+")


@dataclass(frozen=True)
class TopicRules:
    topics: dict[str, dict[str, str]]                 # doc_type → {topic: label}
    headings: dict[str, list[tuple[str, str]]]        # doc_type → [(keyword, topic)], longest first
    role_access: dict[str, dict[str, frozenset[str]]]  # role → doc_type → topics
    role_scope: dict[str, str]                         # role → "company" | "assigned"

    def access_keys(self, role: str) -> frozenset[str]:
        return frozenset(f"{dt}:{t}" for dt, ts in self.role_access.get(role, {}).items() for t in ts)

    def roles_for(self, doc_type: str, topic: str) -> list[str]:
        return [r for r, by_type in self.role_access.items() if topic in by_type.get(doc_type, ())]


def rules_from_dict(raw: dict) -> TopicRules:
    topics = {dt: dict(ts) for dt, ts in raw["topics"].items()}
    headings = {dt: sorted(((k.lower(), t) for k, t in kws.items()), key=lambda kv: -len(kv[0]))
                for dt, kws in raw["topic_headings"].items()}
    for dt, kws in headings.items():
        unknown = {t for _, t in kws} - set(topics[dt])
        if unknown:
            raise ValueError(f"topic_headings[{dt}] uses unknown topics {unknown}")
    role_access, role_scope = {}, {}
    for role, spec in raw["role_access"].items():
        role_scope[role] = spec["scope"]
        role_access[role] = {}
        for dt, ts in spec["topics"].items():
            allowed = set(topics[dt]) if ts == ["*"] else set(ts)
            if allowed - set(topics[dt]):
                raise ValueError(f"role_access[{role}][{dt}] uses unknown topics {allowed - set(topics[dt])}")
            role_access[role][dt] = frozenset(allowed)
    return TopicRules(topics, headings, role_access, role_scope)


ROLE_LABEL = {"ceo": "CEO", "pm": "Project Manager", "developer": "Developer", "qa": "QA Engineer",
              "finance": "Finance Manager", "client": "Client"}


def rules_from_db(conn) -> TopicRules:
    """The live rules as stored in the database (seeded from the YAML)."""
    raw: dict = {"topics": {}, "topic_headings": {}, "role_access": {}}
    for dt, key, label in conn.execute("SELECT doc_type, key, label FROM topics ORDER BY doc_type, ordinal"):
        raw["topics"].setdefault(dt, {})[key] = label
        raw["topic_headings"].setdefault(dt, {})
    for dt, keyword, topic in conn.execute("SELECT doc_type, keyword, topic FROM topic_headings"):
        raw["topic_headings"].setdefault(dt, {})[keyword] = topic
    access: dict = {}
    for role, dt, topic in conn.execute("SELECT role, doc_type, topic FROM role_topic_access"):
        access.setdefault(role, {}).setdefault(dt, []).append(topic)
    for role, scope in conn.execute("SELECT name, scope FROM roles"):
        raw["role_access"][role] = {"scope": scope, "topics": access.get(role, {})}
    return rules_from_dict(raw)


@lru_cache(maxsize=1)
def default_rules() -> TopicRules:
    return rules_from_dict(yaml.safe_load(SEED_FILE.read_text(encoding="utf-8")))


def _normalize(heading: str) -> str:
    text = _NUMBERING.sub("", heading.strip())
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def classify(doc_type: str, heading: str, rules: TopicRules | None = None) -> str:
    rules = rules or default_rules()
    text = _normalize(heading)
    for keyword, topic in rules.headings.get(doc_type, []):
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return topic
    return UNCLASSIFIED


def is_money_line(line: str) -> bool:
    return bool(_CURRENCY.search(line) and _MONEY_WORD.search(line))


def clean_markup(text: str) -> str:
    return _STRAY_TAGS.sub("", text)


def split_commercial(sections: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """(heading, topic, content) list → same, with money lines moved into commercial sections.

    The moved lines go into a new section placed right after their source section, so the reviewer
    sees exactly where each came from. Commercial sections are left untouched.
    """
    out = []
    for heading, topic, content in sections:
        if topic == COMMERCIAL:
            out.append((heading, topic, content))
            continue
        kept, moved = [], []
        subheading = None                                # e.g. "### Plan 2 — AI Integration"
        for line in content.splitlines():
            if line.startswith("### "):
                subheading = line[4:].strip()
            if not (line.strip() and is_money_line(line)):
                kept.append(line)
                continue
            # Several sentences on one line: move only the ones with a price, keep the rest in place.
            sentences = re.split(r"(?<=[.!?])\s+", line.strip())
            money = [s for s in sentences if is_money_line(s)] if len(sentences) > 1 else [line.strip()]
            rest = [s for s in sentences if s not in money] if len(sentences) > 1 else []
            if rest:
                kept.append(" ".join(rest))
            for s in money or [line.strip()]:
                # Keep the context so "Investment: $1,000" still says which plan it belongs to.
                moved.append(f"{subheading}: {s}" if subheading else s)
        remaining = "\n".join(kept).strip()
        if remaining:
            out.append((heading, topic, re.sub(r"\n{3,}", "\n\n", remaining)))
        if moved:
            out.append((f"Commercial details — from {heading}", COMMERCIAL, "\n".join(l.strip() for l in moved)))
    return out
