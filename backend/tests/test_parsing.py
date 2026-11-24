"""Parser round-trip: the 12 demo documents rendered as real DOCX and PDF files must parse back into
the same sections with the same text. Plus edge cases and malicious files."""

import re
import zipfile

import pytest

from app.documents import load_documents
from app.parsing import ParseError, check_docx, detect_kind, parse_file, parse_file_isolated
from app.seed import DOCUMENTS_DIR

from .render_docs import plain, to_docx, to_pdf

DOCS = load_documents(DOCUMENTS_DIR)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", plain(text).lower()))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("rendered")
    return {(d.id, kind): fn(d, out / f"{d.id}.{kind}")
            for d in DOCS for kind, fn in (("docx", to_docx), ("pdf", to_pdf))}


@pytest.mark.parametrize("kind", ["docx", "pdf"])
@pytest.mark.parametrize("doc", DOCS, ids=[d.id for d in DOCS])
def test_round_trip(rendered, doc, kind):
    path = rendered[(doc.id, kind)]
    assert detect_kind(path) == kind
    parsed = parse_file(path, kind)

    assert [s.heading for s in parsed.sections] == [plain(s.heading) for s in doc.sections]
    assert parsed.title and plain(doc.title).startswith(parsed.title[:30])
    for want, got in zip(doc.sections, parsed.sections):
        a, b = tokens(want.content), tokens(got.content)
        overlap = len(a & b) / len(a | b)
        assert overlap >= 0.9, f"{doc.id} {kind} '{want.heading}': {overlap:.2f}, missing {sorted(a - b)[:8]}, extra {sorted(b - a)[:8]}"
    everything = "\n".join(s.content for s in parsed.sections)
    assert "Confidential — Page" not in everything            # footer stripped
    assert ".........." not in everything                     # table of contents stripped


def test_tables_survive_as_markdown(rendered):
    for kind in ("docx", "pdf"):
        parsed = parse_file(rendered[("p001-brd", kind)], kind)
        milestones = next(s for s in parsed.sections if s.heading == "5. Delivery Milestones")
        assert re.search(r"^\| *M6 *\| *Go-live", milestones.content, re.M), kind


def test_isolated_parse_matches_in_process(rendered):
    path = rendered[("p001-qa-report", "pdf")]
    assert parse_file_isolated(path, "pdf").sections == parse_file(path, "pdf").sections


# --- Edge cases ---------------------------------------------------------------------------------

def test_pdf_without_headings_falls_back_to_pages(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(path))
    for n in range(3):
        c.setFont("Helvetica", 10)
        c.drawString(72, 700, f"Plain body text on page {n + 1} with no headings at all.")
        c.showPage()
    c.save()
    parsed = parse_file(path, "pdf")
    assert parsed.used_page_fallback and [s.heading for s in parsed.sections] == ["Page 1", "Page 2", "Page 3"]


def test_scanned_pdf_without_text_is_rejected(tmp_path):
    from reportlab.pdfgen import canvas
    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path))
    c.rect(50, 50, 400, 600, fill=1)       # an "image" of a page, no text
    c.showPage()
    c.save()
    with pytest.raises(ParseError, match="no text layer"):
        parse_file(path, "pdf")


def test_docx_heading_levels_use_most_frequent_as_boundary(tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("Big Title", style="Title")
    d.add_paragraph("Cover note before any heading.")
    d.add_paragraph("Chapter", style="Heading 1")
    for i in range(3):
        d.add_paragraph(f"Part {i}", style="Heading 2")
        d.add_paragraph(f"Body {i}")
        d.add_paragraph(f"Detail {i}", style="Heading 3")
        d.add_paragraph(f"Detail body {i}")
    path = tmp_path / "levels.docx"
    d.save(str(path))
    parsed = parse_file(path, "docx")
    assert parsed.title == "Big Title"
    assert [s.heading for s in parsed.sections] == ["Introduction", "Part 0", "Part 1", "Part 2"]
    assert "### Detail 0" in parsed.sections[1].content
    assert "Chapter" in parsed.sections[0].content or "Cover note" in parsed.sections[0].content


# --- Malicious or wrong files -------------------------------------------------------------------

def test_file_type_is_decided_by_content_not_name(tmp_path):
    fake = tmp_path / "invoice.pdf"
    fake.write_bytes(b"MZ\x90\x00 this is really an exe")
    with pytest.raises(ParseError, match="Only PDF and Word"):
        detect_kind(fake)


def test_zip_that_is_not_a_word_file_is_rejected(tmp_path):
    path = tmp_path / "x.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(ParseError, match="Only PDF and Word"):
        detect_kind(path)


def test_zip_bomb_is_rejected_before_unpacking(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("word/media/huge.bin", b"\0" * (101 * 1024 * 1024))   # compresses to ~100 KB
    assert path.stat().st_size < 1024 * 1024
    with pytest.raises(ParseError, match="too large once unpacked"):
        check_docx(path)


def test_too_many_zip_entries_is_rejected(tmp_path):
    path = tmp_path / "many.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        for i in range(1001):
            z.writestr(f"word/x{i}.xml", "x")
    with pytest.raises(ParseError, match="too many parts"):
        check_docx(path)


def test_corrupt_pdf_gives_a_clear_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\n garbage that is not a pdf")
    with pytest.raises(ParseError):
        parse_file_isolated(path, "pdf")


def test_parser_timeout_is_enforced(tmp_path, rendered):
    with pytest.raises(ParseError, match="longer than"):
        parse_file_isolated(rendered[("p001-brd", "pdf")], "pdf", timeout=0.01)
