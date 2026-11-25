"""Render the Markdown demo documents to real DOCX and PDF files for parser round-trip tests.

Each output has what real business documents have: a title, a table of contents with dot leaders and
page numbers, numbered section headings, bullet lists, tables, and (PDF) a repeated
"XYZ Software — Confidential — Page N" footer. The parser must recover the original sections.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.documents import Document

_INLINE = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`")


def plain(text: str) -> str:
    """Markdown inline formatting removed (what a reader sees)."""
    return _INLINE.sub(lambda m: next(g for g in m.groups() if g is not None), text)


def _blocks(content: str):
    """Yield ("table", rows) | ("bullet", text) | ("subheading", text) | ("para", text)."""
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [plain(c.strip()) for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"-+", c) for c in cells):
                    rows.append(cells)
                i += 1
            yield "table", rows
            continue
        if line.startswith("### "):
            yield "subheading", plain(line[4:])
        elif re.match(r"^\s*([-*]|\d+\.)\s", line):
            number = re.match(r"^\s*(\d+\.)\s", line)          # keep "1." on numbered items
            text = (number.group(1) + " " if number else "") + re.sub(r"^\s*([-*]|\d+\.)\s+", "", line)
            while i + 1 < len(lines) and lines[i + 1].startswith("  ") and lines[i + 1].strip():
                i += 1
                text += " " + lines[i].strip()
            yield "bullet", plain(text)
        else:
            para = [line.strip()]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(\||#|\s*[-*]\s|\s*\d+\.\s)", lines[i + 1]):
                i += 1
                para.append(lines[i].strip())
            yield "para", plain(" ".join(para))
        i += 1


def to_docx(doc: Document, path: Path) -> Path:
    from docx import Document as new_docx

    d = new_docx()
    d.add_paragraph(plain(doc.title), style="Title")
    d.add_paragraph("Contents")
    for n, s in enumerate(doc.sections, start=1):
        d.add_paragraph(f"{plain(s.heading)} .......... {n + 1}")
    for s in doc.sections:
        d.add_paragraph(plain(s.heading), style="Heading 2")
        for kind, value in _blocks(s.content):
            if kind == "table":
                table = d.add_table(rows=len(value), cols=max(len(r) for r in value))
                for r, row in enumerate(value):
                    for c, cell in enumerate(row):
                        table.cell(r, c).text = cell
            elif kind == "bullet":
                d.add_paragraph(value, style="List Bullet")
            elif kind == "subheading":
                d.add_paragraph(value, style="Heading 3")
            else:
                d.add_paragraph(value)
    d.save(str(path))
    return path


def to_pdf(doc: Document, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=6)
    h_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=12)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=10, spaceAfter=6)
    h3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11.5, leading=14, spaceBefore=6, spaceAfter=4)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5)

    story = [Paragraph(escape(plain(doc.title)), h_title), Paragraph("Contents", body)]
    for n, s in enumerate(doc.sections, start=1):
        story.append(Paragraph(escape(f"{plain(s.heading)} .......... {n + 1}"), body))
    story.append(PageBreak())
    for s in doc.sections:
        story.append(Paragraph(escape(plain(s.heading)), h2))
        for kind, value in _blocks(s.content):
            if kind == "table":
                width = max(len(r) for r in value)
                data = [[Paragraph(escape(c), cell) for c in r + [""] * (width - len(r))] for r in value]
                t = Table(data, colWidths=[480 / width] * width)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
                story += [t, Spacer(1, 6)]
            elif kind == "bullet":
                story.append(Paragraph("• " + escape(value), body))
            elif kind == "subheading":
                story.append(Paragraph(escape(value), h3))
            else:
                story.append(Paragraph(escape(value), body))

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(72, 30, f"XYZ Software — Confidential — Page {d.page}")

    SimpleDocTemplate(str(path), pagesize=A4).build(story, onFirstPage=footer, onLaterPages=footer)
    return path
