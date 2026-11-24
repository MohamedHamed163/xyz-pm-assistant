"""Parse source documents into sections and chunks.

Rules (see docs/design-decisions.md §3):
- A section starts at every level-2 heading (``## ...``).
- Visibility is set on the heading line: ``<!-- visibility: client_shared -->``.
  Unmarked sections are ``internal`` (deny by default). Unknown values fail loudly.
- A chunk never crosses a section boundary, so it always inherits exactly one visibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

INTERNAL = "internal"
CLIENT_SHARED = "client_shared"
VISIBILITIES = frozenset({INTERNAL, CLIENT_SHARED})

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_VISIBILITY_MARKER = re.compile(r"<!--\s*visibility:\s*([\w-]+)\s*-->")


class DocumentParseError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    ordinal: int
    heading: str
    visibility: str
    content: str


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    project_id: str | None
    doc_type: str
    version: str
    company_id: str = "xyz"
    status: str = "ready"
    sections: tuple[Section, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    section_ordinal: int
    company_id: str
    project_id: str | None
    doc_type: str
    visibility: str
    status: str
    heading: str
    text: str


def parse_document(source: str, *, company_id: str = "xyz") -> Document:
    match = _FRONT_MATTER.match(source)
    if not match:
        raise DocumentParseError("missing YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    for key in ("id", "title", "doc_type"):
        if not meta.get(key):
            raise DocumentParseError(f"front matter is missing '{key}'")

    body = source[match.end():]
    sections = _split_sections(body, doc_id=meta["id"])
    return Document(
        id=meta["id"],
        title=meta["title"],
        project_id=meta.get("project"),
        doc_type=meta["doc_type"],
        version=str(meta.get("version", "1")),
        company_id=company_id,
        status=meta.get("status", "ready"),
        sections=tuple(sections),
    )


def load_document(path: Path, *, company_id: str = "xyz") -> Document:
    return parse_document(path.read_text(encoding="utf-8"), company_id=company_id)


def load_documents(root: Path, *, company_id: str = "xyz") -> list[Document]:
    docs = [load_document(p, company_id=company_id) for p in sorted(root.rglob("*.md"))]
    ids = [d.id for d in docs]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise DocumentParseError(f"duplicate document ids: {sorted(duplicates)}")
    return docs


def _split_sections(body: str, *, doc_id: str) -> list[Section]:
    sections: list[Section] = []
    heading, visibility, lines = None, INTERNAL, []
    in_fence = False

    def flush() -> None:
        content = "\n".join(lines).strip()
        if heading is None:
            # Preamble before the first "##": keep it only if it has more than the "# Title" line.
            content = "\n".join(l for l in lines if not l.startswith("# ")).strip()
            if not content:
                return
        sections.append(Section(len(sections), heading or "Introduction", visibility, content))

    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            flush()
            heading, visibility = _parse_heading(line[3:], doc_id=doc_id)
            lines = []
        else:
            lines.append(line)
    flush()
    return sections


def _parse_heading(raw: str, *, doc_id: str) -> tuple[str, str]:
    marker = _VISIBILITY_MARKER.search(raw)
    visibility = INTERNAL
    if marker:
        visibility = marker.group(1)
        if visibility not in VISIBILITIES:
            raise DocumentParseError(f"{doc_id}: unknown visibility '{visibility}' in heading '{raw}'")
    return _VISIBILITY_MARKER.sub("", raw).strip(), visibility


def chunk_document(doc: Document, *, max_chars: int = 1200) -> list[Chunk]:
    """Split each section into chunks of at most ~max_chars, on paragraph boundaries.

    Chunks never span two sections. Each chunk's text is prefixed with the document title and
    section heading so the embedding and the LLM both know where it came from.
    """
    chunks: list[Chunk] = []
    for section in doc.sections:
        for n, piece in enumerate(_split_text(section.content, max_chars)):
            chunks.append(Chunk(
                id=f"{doc.id}#s{section.ordinal}c{n}",
                document_id=doc.id,
                section_ordinal=section.ordinal,
                company_id=doc.company_id,
                project_id=doc.project_id,
                doc_type=doc.doc_type,
                visibility=section.visibility,
                status=doc.status,
                heading=section.heading,
                text=f"{doc.title} — {section.heading}\n\n{piece}",
            ))
    return chunks


def _split_text(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > max_chars:  # a single oversized paragraph: hard split
            if current:
                pieces.append(current)
                current = ""
            pieces.append(para[:max_chars])
            para = para[max_chars:]
        if current and len(current) + 2 + len(para) > max_chars:
            pieces.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces
