import pytest

from app.documents import (
    CLIENT_SHARED,
    INTERNAL,
    DocumentParseError,
    chunk_document,
    parse_document,
)


def test_all_demo_documents_load(documents):
    assert len(documents) == 12
    assert {d.doc_type for d in documents} == {"brd", "prd", "technical", "qa", "contract", "executive_report"}


def test_company_wide_report_has_no_project(documents):
    report = next(d for d in documents if d.id == "company-profitability-2026")
    assert report.project_id is None


def test_unmarked_sections_default_to_internal(documents):
    brd = next(d for d in documents if d.id == "p001-brd")
    vis = {s.heading: s.visibility for s in brd.sections}
    assert vis["5. Delivery Milestones"] == CLIENT_SHARED
    assert vis["7. Internal Delivery Risks"] == INTERNAL


def test_documents_without_any_markers_are_fully_internal(documents):
    for doc_id in ("p001-tech-architecture", "p001-qa-report", "p002-api-docs", "company-profitability-2026"):
        doc = next(d for d in documents if d.id == doc_id)
        assert all(s.visibility == INTERNAL for s in doc.sections), doc_id


def test_unknown_visibility_value_fails_loudly():
    src = "---\nid: x\ntitle: X\ndoc_type: brd\n---\n## A <!-- visibility: public -->\ntext\n"
    with pytest.raises(DocumentParseError):
        parse_document(src)


def test_missing_front_matter_fails():
    with pytest.raises(DocumentParseError):
        parse_document("## A\ntext\n")


def test_chunks_never_cross_sections_and_inherit_visibility(documents):
    for doc in documents:
        sections = {s.ordinal: s for s in doc.sections}
        for chunk in chunk_document(doc, max_chars=200):  # small size forces many splits
            section = sections[chunk.section_ordinal]
            assert chunk.visibility == section.visibility
            body = chunk.text.split("\n\n", 1)[1]
            assert body in section.content or all(part in section.content for part in body.split("\n\n"))


def test_shared_and_internal_text_never_share_a_chunk(documents):
    contract = next(d for d in documents if d.id == "p001-client-contract")
    for chunk in chunk_document(contract, max_chars=5000):  # huge size: would merge if allowed
        has_internal_fact = "USD 352,000" in chunk.text
        if has_internal_fact:
            assert chunk.visibility == INTERNAL
            assert "USD 486,000" not in chunk.text


def test_heading_inside_code_fence_is_not_a_section():
    src = "---\nid: x\ntitle: X\ndoc_type: technical\n---\n## Real\n```\n## not a heading\n```\n"
    doc = parse_document(src)
    assert [s.heading for s in doc.sections] == ["Real"]
