"""Parse uploaded PDF / DOCX files into sections (upload-feature design Q2, Q7, Q8, Q9).

- DOCX: Word heading styles ("Heading 1..9", "Title") mark sections.
- PDF: headings are guessed from font size and boldness; table-of-contents lines and headers/footers
  repeated on most pages are removed; with no headings at all, each page becomes a section.
- The most frequent heading level is the section boundary; deeper headings stay inside a section
  (as "### …"); text before the first boundary heading becomes "Introduction".
- Tables become Markdown tables.
- Limits: 300 pages, 500 sections, DOCX ≤ 100 MB unpacked and ≤ 1,000 zip entries.
- Untrusted files are parsed in a separate process with a timeout and memory cap
  (``parse_file_isolated``). Nothing in a file is ever executed — only text is extracted.

Run as a module for the isolated child process:  python -m app.parsing <path> <pdf|docx>
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_PAGES = 300
MAX_SECTIONS = 500
DOCX_MAX_UNPACKED = 100 * 1024 * 1024
DOCX_MAX_ENTRIES = 1000
PARSE_TIMEOUT = 60
MEMORY_LIMIT = 1024 * 1024 * 1024   # 1 GB for the parser process

BACKEND_DIR = Path(__file__).resolve().parents[1]


class ParseError(ValueError):
    """A problem with the file, explained in words the uploader can act on."""


@dataclass
class ParsedSection:
    heading: str
    content: str


@dataclass
class ParsedDocument:
    title: str | None
    sections: list[ParsedSection]
    page_count: int | None = None
    used_page_fallback: bool = False


@dataclass
class _Block:
    kind: str            # "heading" | "text" | "table"
    text: str
    level: int = 0       # headings: 0 = title, 1 = top level, …
    page: int = 0
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------------------------

def detect_kind(path: Path) -> str:
    """Decide by content, never by file name. Raises ParseError for anything else."""
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        check_docx(path)
        return "docx"
    raise ParseError("Only PDF and Word (.docx) files can be uploaded.")


def check_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except zipfile.BadZipFile:
        raise ParseError("This Word file is damaged and can't be opened.")
    if not any(i.filename == "word/document.xml" for i in infos):
        raise ParseError("Only PDF and Word (.docx) files can be uploaded.")
    if len(infos) > DOCX_MAX_ENTRIES:
        raise ParseError("This Word file contains too many parts to process safely.")
    if sum(i.file_size for i in infos) > DOCX_MAX_UNPACKED:
        raise ParseError("This Word file is too large once unpacked (over 100 MB).")


# ---------------------------------------------------------------------------------------------
# Isolated parsing
# ---------------------------------------------------------------------------------------------

def _limit_resources() -> None:  # runs in the child before exec
    import resource
    for limit, value in ((resource.RLIMIT_CPU, PARSE_TIMEOUT + 5), (resource.RLIMIT_AS, MEMORY_LIMIT)):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass  # not supported on this OS (e.g. RLIMIT_AS on macOS); the timeout still applies


def parse_file_isolated(path: Path, kind: str, *, timeout: float = PARSE_TIMEOUT) -> ParsedDocument:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.parsing", str(path), kind],
            cwd=BACKEND_DIR, capture_output=True, text=True, timeout=timeout,
            preexec_fn=_limit_resources,
        )
    except subprocess.TimeoutExpired:
        raise ParseError(f"Parsing took longer than {int(timeout)} seconds. Try a smaller file.")
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise ParseError("This file could not be read.")
    if "error" in data:
        raise ParseError(data["error"])
    return ParsedDocument(
        title=data["title"], page_count=data["page_count"], used_page_fallback=data["used_page_fallback"],
        sections=[ParsedSection(**s) for s in data["sections"]],
    )


def parse_file(path: Path, kind: str) -> ParsedDocument:
    doc = parse_pdf(path) if kind == "pdf" else parse_docx(path)
    if not doc.sections:
        raise ParseError("No text was found in this file.")
    if len(doc.sections) > MAX_SECTIONS:
        raise ParseError(f"This file has more than {MAX_SECTIONS} sections. Split it into smaller documents.")
    return doc


# ---------------------------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------------------------

def parse_docx(path: Path) -> ParsedDocument:
    from docx import Document as load_docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    check_docx(path)
    try:
        d = load_docx(str(path))
    except Exception:
        raise ParseError("This Word file is damaged and can't be opened.")

    blocks: list[_Block] = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = p.text.strip()
            if not text or _is_toc_line(text):
                continue
            style = (p.style.name if p.style is not None else "") or ""
            level = _docx_heading_level(style)
            if level is not None:
                blocks.append(_Block("heading", text, level))
            elif "List" in style:
                blocks.append(_Block("text", f"- {text}"))
            else:
                blocks.append(_Block("text", text))
        elif tag == "tbl":
            rows = [[cell.text for cell in row.cells] for row in Table(child, d).rows]
            if rows:
                blocks.append(_Block("table", _markdown_table(rows)))
    title, sections = _sectionize(blocks)
    if not sections:
        text = "\n\n".join(b.text for b in blocks)
        sections = [ParsedSection("Document", text)] if text.strip() else []
    return ParsedDocument(title, sections)


def _docx_heading_level(style: str) -> int | None:
    if style == "Title":
        return 0
    m = re.match(r"Heading (\d)", style)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------------------------

_TOC_LINE = re.compile(r"(\.{3,}|…{2,}|\s\.\s\.\s)\s*\d{1,4}\s*$")
_TOC_LABEL = re.compile(r"^(table of )?contents$", re.I)
_PAGE_NUMBER = re.compile(r"(^|\s)(page\s*)?#(\s*(of|/)\s*#)?$|^-\s*#\s*-$", re.I)
_CID = re.compile(r"\(cid:\d+\)")


def _is_toc_line(text: str) -> bool:
    return bool(_TOC_LINE.search(text) or _TOC_LABEL.match(text.strip()))
_NUMBERED = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z]\.)\s+\S")


def parse_pdf(path: Path) -> ParsedDocument:
    import pdfplumber

    try:
        pdf = pdfplumber.open(str(path))
    except Exception:
        raise ParseError("This PDF is damaged or password-protected and can't be opened.")
    with pdf:
        pages = pdf.pages
        if len(pages) > MAX_PAGES:
            raise ParseError(f"This PDF has {len(pages)} pages; the limit is {MAX_PAGES}.")
        page_lines, page_tables, heights = [], [], []
        for page in pages:
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            words = page.extract_words(extra_attrs=["size", "fontname"], use_text_flow=True)
            words = [w for w in words if not any(_inside(w, b) for b in boxes)]
            page_lines.append(_group_lines(words))
            page_tables.append([(t.bbox[1], _markdown_table(t.extract())) for t in tables if t.extract()])
            heights.append(page.height)

    if not any(page_lines) and not any(page_tables):
        raise ParseError("This PDF has no text layer (it looks scanned). Export it as text or upload the DOCX.")

    _drop_repeated_margins(page_lines, heights)
    body = _body_size(page_lines)
    blocks = _pdf_blocks(page_lines, page_tables, body)
    title, sections = _sectionize(blocks)
    if sections:
        return ParsedDocument(title, sections, page_count=len(page_lines))

    # No headings at all: one section per page.
    per_page = []
    for n in range(len(page_lines)):
        text = "\n\n".join(b.text for b in blocks if b.page == n)
        if text.strip():
            per_page.append(ParsedSection(f"Page {n + 1}", text))
    return ParsedDocument(title, per_page, page_count=len(page_lines), used_page_fallback=True)


def _inside(word: dict, box) -> bool:
    x0, top, x1, bottom = box
    return word["x0"] >= x0 - 1 and word["x1"] <= x1 + 1 and word["top"] >= top - 1 and word["bottom"] <= bottom + 1


def _group_lines(words: list[dict]) -> list[dict]:
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) <= 2.5:
            line = lines[-1]
            line["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    out = []
    for line in lines:
        ws = sorted(line["words"], key=lambda w: w["x0"])
        text = _CID.sub("•", " ".join(w["text"] for w in ws)).strip()
        if not text:
            continue
        out.append({
            "text": text,
            "top": line["top"],
            "bottom": max(w["bottom"] for w in ws),
            "size": round(max(w["size"] for w in ws) * 2) / 2,
            "bold": all("bold" in w["fontname"].lower() or "black" in w["fontname"].lower() for w in ws),
        })
    return out


def _drop_repeated_margins(page_lines: list[list[dict]], heights: list[float]) -> None:
    """Remove headers/footers: lines in the top/bottom 12% of the page that repeat on most pages."""
    n = len(page_lines)
    norm = lambda t: re.sub(r"\d+", "#", t.lower()).strip()
    margin = lambda l, h: l["top"] < 0.12 * h or l["bottom"] > 0.88 * h
    counts = Counter()
    for lines, h in zip(page_lines, heights):
        counts.update({norm(l["text"]) for l in lines if margin(l, h)})
    # Repeated = on both pages of a 2-page document, or on more than half the pages otherwise.
    repeated = {t for t, c in counts.items() if (n == 2 and c == 2) or (n >= 3 and c > n / 2)}
    for i, (lines, h) in enumerate(zip(page_lines, heights)):
        page_lines[i] = [l for l in lines if not (
            margin(l, h) and (norm(l["text"]) in repeated or _PAGE_NUMBER.search(norm(l["text"]))))]


def _body_size(page_lines: list[list[dict]]) -> float:
    weights = Counter()
    for lines in page_lines:
        for l in lines:
            weights[l["size"]] += len(l["text"])
    return weights.most_common(1)[0][0] if weights else 10.0


def _pdf_blocks(page_lines, page_tables, body: float) -> list[_Block]:
    # Heading candidates: noticeably larger than body text, or bold short numbered lines.
    def is_heading(l):
        text = l["text"]
        if _TOC_LINE.search(text) or len(text) > 120:
            return False
        if l["size"] >= body * 1.15:
            return True
        return l["bold"] and len(text) <= 90 and bool(_NUMBERED.match(text)) and not text.endswith(".")

    sizes = sorted({l["size"] for lines in page_lines for l in lines if is_heading(l)}, reverse=True)
    level_of_size = {s: i + 1 for i, s in enumerate(sizes)}

    blocks: list[_Block] = []
    for page_no, (lines, tables) in enumerate(zip(page_lines, page_tables)):
        items = [("line", l["top"], l) for l in lines] + [("table", top, md) for top, md in tables]
        para: list[str] = []
        last_bottom = None

        def flush():
            if para:
                blocks.append(_Block("text", " ".join(para), page=page_no))
                para.clear()

        for kind, _, item in sorted(items, key=lambda x: x[1]):
            if kind == "table":
                flush()
                blocks.append(_Block("table", item, page=page_no))
                last_bottom = None
                continue
            l = item
            if _is_toc_line(l["text"]):
                continue
            if is_heading(l):
                flush()
                level = level_of_size[l["size"]]
                prev = blocks[-1] if blocks else None
                if (prev and prev.kind == "heading" and prev.level == level and prev.page == page_no
                        and last_bottom is not None and l["top"] - last_bottom < l["size"] * 0.6):
                    prev.text = f"{prev.text} {l['text']}"          # heading wrapped onto two lines
                else:
                    blocks.append(_Block("heading", l["text"], level, page=page_no))
                last_bottom = l["bottom"]
                continue
            text = l["text"]
            starts_item = bool(re.match(r"^([•▪◦\-–*]|\d+[.)])\s", text))
            gap = (l["top"] - last_bottom) if last_bottom is not None else 0
            if starts_item or gap > l["size"] * 0.5:      # paragraph spacing; line spacing is ~0.2× size
                flush()
            if starts_item:
                text = "- " + re.sub(r"^[•▪◦\-–*]\s*", "", text)
            para.append(text)
            last_bottom = l["bottom"]
        flush()
    # A single largest heading that comes first is the document title.
    heads = [b for b in blocks if b.kind == "heading"]
    if heads and heads[0].level == 1 and sum(1 for b in heads if b.level == 1) == 1 and len(sizes) > 1:
        heads[0].level = 0
    return blocks


# ---------------------------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------------------------

def _sectionize(blocks: list[_Block]) -> tuple[str | None, list[ParsedSection]]:
    title = next((b.text for b in blocks if b.kind == "heading" and b.level == 0), None)
    levels = Counter(b.level for b in blocks if b.kind == "heading" and b.level >= 1)
    if not levels:
        return title, []
    top = max(levels.values())
    boundary = min(level for level, count in levels.items() if count == top)

    sections: list[ParsedSection] = []
    heading, parts = "Introduction", []

    def flush():
        content = "\n\n".join(parts).strip()
        if content:
            sections.append(ParsedSection(heading, content))

    for b in blocks:
        if b.kind == "heading" and b.level == 0:
            continue
        if b.kind == "heading" and b.level <= boundary:
            flush()
            heading, parts = b.text, []
        elif b.kind == "heading":
            parts.append(f"### {b.text}")
        else:
            parts.append(b.text)
    flush()
    return title, sections


def _markdown_table(rows: list[list]) -> str:
    clean = [[re.sub(r"\s+", " ", str(c or "")).replace("|", "\\|").strip() for c in row] for row in rows]
    width = max(len(r) for r in clean)
    clean = [r + [""] * (width - len(r)) for r in clean]
    lines = ["| " + " | ".join(clean[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in clean[1:]]
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    path, kind = Path(argv[0]), argv[1]
    try:
        doc = parse_file(path, kind)
        print(json.dumps(asdict(doc)))
    except ParseError as exc:
        print(json.dumps({"error": str(exc)}))
    except MemoryError:
        print(json.dumps({"error": "This file is too complex to process."}))
    except Exception:
        print(json.dumps({"error": "This file could not be read."}))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
