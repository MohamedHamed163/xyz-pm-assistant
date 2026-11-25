import pytest

from app.documents import DocumentParseError, chunk_document, parse_document
from app.topics import classify, is_money_line, split_commercial


def test_sample_corpus_loads(documents):
    assert len(documents) == 6
    assert {d.doc_type for d in documents} == {"brd", "prd", "proposal"}
    assert {d.project_id for d in documents} == {"P001", "P002"}


def test_no_sample_section_is_unclassified(documents):
    assert not [(d.id, s.heading) for d in documents for s in d.sections if s.topic == "unclassified"]


@pytest.mark.parametrize("doc_type,heading,topic", [
    ("brd", "11. Business Rules", "business_rules"),
    ("brd", "4. Business Goals & Objectives", "goals"),
    ("brd", "17. Business Acceptance / Sign-Off", "governance"),
    ("brd", "10. Business Process / High-Level User Journey", "requirements"),
    ("prd", "9. Non-Functional Requirements", "requirements"),
    ("prd", "13. MVP Release Criteria", "delivery"),
    ("proposal", "4. Project Delivery Plans", "scope"),
    ("proposal", "Plan 2 — AI Integration & Intelligent Document Chat", "scope"),
    ("proposal", "6. Commercial Proposal", "commercial"),
    ("proposal", "12. Proposal Approval", "completion"),
    ("brd", "Appendix Z — Glossary", "unclassified"),
    ("prd", "Platform notes", "unclassified"),          # "plan" must not match inside "Platform"
])
def test_heading_keywords(doc_type, heading, topic):
    assert classify(doc_type, heading) == topic


@pytest.mark.parametrize("line,money", [
    ("Investment: $1,000", True),
    ("Total Project Investment: $3,000 USD", True),
    ("Payment terms: AED 140,000 in two milestones", True),
    ("The system validates file type and size.", False),
    ("99.5% monthly availability", False),
    ("Plan 2 costs a lot of effort", False),        # money word, no amount
    ("Released on 2026-12-05 for 1,200 students", False),  # amount-like numbers, no currency
])
def test_money_lines(line, money):
    assert is_money_line(line) is money


def test_split_commercial_moves_only_price_lines_and_keeps_order():
    out = split_commercial([("4. Plans", "scope", "Plan 1 scope.\nInvestment: $1,000\nAcceptance criteria."),
                            ("6. Commercial", "commercial", "Total $3,000")])
    assert out == [("4. Plans", "scope", "Plan 1 scope.\nAcceptance criteria."),
                   ("Commercial details — from 4. Plans", "commercial", "Investment: $1,000"),
                   ("6. Commercial", "commercial", "Total $3,000")]


def test_topic_marker_overrides_and_unknown_topic_fails():
    src = "---\nid: x\ntitle: X\ndoc_type: brd\n---\n## Odd heading <!-- topic: risks -->\ntext\n"
    assert parse_document(src).sections[0].topic == "risks"
    with pytest.raises(DocumentParseError):
        parse_document(src.replace("risks", "secrets"))


def test_unknown_document_type_fails():
    with pytest.raises(DocumentParseError, match="unknown document type"):
        parse_document("---\nid: x\ntitle: X\ndoc_type: minutes\n---\n## A\ntext\n")


def test_missing_front_matter_fails():
    with pytest.raises(DocumentParseError):
        parse_document("## A\ntext\n")


def test_chunks_never_cross_sections_and_inherit_topic(documents):
    for doc in documents:
        sections = {s.ordinal: s for s in doc.sections}
        for chunk in chunk_document(doc, max_chars=200):
            assert chunk.topic == sections[chunk.section_ordinal].topic


def test_heading_inside_code_fence_is_not_a_section():
    src = "---\nid: x\ntitle: X\ndoc_type: prd\n---\n## Scope\n```\n## not a heading\n```\n"
    assert [s.heading for s in parse_document(src).sections] == ["Scope"]


def test_split_lines_keep_their_sub_heading():
    content = "### Plan 1 — Foundation\nScope one.\nInvestment: $1,000\n### Plan 2 — AI\nScope two.\nInvestment: $1,000"
    out = split_commercial([("4. Project Delivery Plans", "scope", content)])
    assert out[1] == ("Commercial details — from 4. Project Delivery Plans", "commercial",
                      "Plan 1 — Foundation: Investment: $1,000\nPlan 2 — AI: Investment: $1,000")
    assert "$" not in out[0][2] and "### Plan 2 — AI" in out[0][2]


def test_only_the_price_sentence_moves_when_a_line_has_several():
    out = split_commercial([("1. Executive Summary", "summary",
                             "We build the store in three plans. Total Project Investment: $18,000 USD. Launch is in Q4.")])
    assert out[0] == ("1. Executive Summary", "summary", "We build the store in three plans. Launch is in Q4.")
    assert out[1][2] == "Total Project Investment: $18,000 USD."
