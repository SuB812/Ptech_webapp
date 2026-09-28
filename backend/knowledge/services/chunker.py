"""Parent-child chunking (FR-09, specs/05-rag-pipeline.md section 3).

Search hits children, the LLM receives parents: search narrow, deliver wide.
A bare ``방수·방진 등급: IP65`` cannot say whether that is LT-150 or LT-200,
standard or optional; the whole table can. Embedding the whole table instead
would blur the vector until a narrow query like ``염수분무`` stops matching.

Produces plain dataclasses. Persistence lives in Phase 4 so this stays testable
without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from common.enums import ChunkType
from knowledge.services.keywords import extract_keywords, extract_models
from knowledge.services.md_parse import MdDocument, MdSection, MdTable

# Chunk sizing (specs/05-rag-pipeline.md section 3.2).
PARENT_MAX_TOKENS = 1200
CHILD_TARGET_TOKENS = 250
CHILD_MIN_TOKENS = 120
CHILD_OVERLAP_TOKENS = 40

# Korean text runs roughly 1.5 characters per token on modern BPE tokenizers.
# Sizing only needs to be approximate, so this avoids taking on a tokenizer
# dependency just to split paragraphs.
CHARS_PER_TOKEN = 1.5

_SENTENCE_SPLIT = re.compile(r"(?<=다\.)\s+|(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*[-*]\s+")


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class ChunkSpec:
    """One chunk, ready to persist."""

    content: str
    section_path: str
    heading: str
    chunk_type: str
    is_parent: bool = False
    page_no: int | None = None
    keywords: list[str] = field(default_factory=list)
    model_tags: list[str] = field(default_factory=list)
    children: list["ChunkSpec"] = field(default_factory=list)

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.content)

    def embedding_input(self) -> str:
        """Text actually embedded: heading path first, then content.

        Including the path is what puts ``LT-150`` into the vector for a row that
        never names it (specs/05-rag-pipeline.md section 4).
        """
        return f"{self.section_path}\n{self.content}" if self.section_path else self.content


# ---------------------------------------------------------------------------
# model_tags
# ---------------------------------------------------------------------------


def resolve_model_tags(section: MdSection, content: str = "") -> list[str]:
    """Which product model a chunk belongs to (specs/05-rag-pipeline.md 3.5).

    Heading path wins; otherwise the model named in the content; otherwise empty,
    meaning model-agnostic. An empty list must never be penalised by the
    retriever's model filter -- supply terms and certifications are common to
    every model and would otherwise be filtered away from every query.
    """
    from_path = section.model_tags
    if from_path:
        return from_path
    return extract_models(content)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _row_to_sentence(table: MdTable, row: list[str], heading: str) -> str:
    """Turn a table row into something embeddable.

    ``| IP65 |`` on its own embeds badly. Prefixing the column header and the
    heading makes it read like a sentence, so ``방수 등급이 뭐야`` lands near it
    (specs/05-rag-pipeline.md section 3.2).
    """
    header = table.header
    pairs = []
    for index, cell in enumerate(row):
        if not cell:
            continue
        label = header[index] if index < len(header) else ""
        pairs.append(f"{label}: {cell}" if label else cell)
    body = ", ".join(pairs)
    return f"{heading} — {body}" if heading else body


def _table_to_markdown(table: MdTable) -> str:
    from common.tables import to_markdown

    return to_markdown(table.rows)


def chunk_table(table: MdTable, section: MdSection) -> ChunkSpec:
    """One table becomes one parent; each body row becomes one child.

    Tables are never split -- that one-to-one mapping is what lets the LLM see
    full context while search stays row-level.
    """
    heading = section.heading or (table.heading_path[-1] if table.heading_path else "")
    parent_content = _table_to_markdown(table)

    parent = ChunkSpec(
        content=parent_content,
        section_path=table.section_path,
        heading=heading,
        chunk_type=ChunkType.TABLE,
        is_parent=True,
        keywords=extract_keywords(parent_content, table.section_path),
        model_tags=resolve_model_tags(section, parent_content),
    )

    for row in table.body:
        if not any(cell.strip() for cell in row):
            continue
        content = _row_to_sentence(table, row, heading)
        parent.children.append(
            ChunkSpec(
                content=content,
                section_path=table.section_path,
                heading=heading,
                chunk_type=ChunkType.TABLE_ROW,
                keywords=extract_keywords(content),
                # Per-row models: the 납품실적 table names a model in its 품목
                # column, so each record carries its own tag.
                model_tags=resolve_model_tags(section, content),
            )
        )

    return parent


# ---------------------------------------------------------------------------
# Narrative text
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = _BULLET.sub("", stripped)
        parts.extend(s.strip() for s in _SENTENCE_SPLIT.split(stripped) if s.strip())
    return parts


def _group_sentences(sentences: list[str]) -> list[str]:
    """Group into 120-250 token children with a ~40 token overlap."""
    if not sentences:
        return []

    groups: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        current.append(sentence)
        if estimate_tokens(" ".join(current)) >= CHILD_TARGET_TOKENS:
            groups.append(" ".join(current))
            # Carry the tail forward so a fact spanning the boundary stays
            # findable from either side.
            overlap: list[str] = []
            for previous in reversed(current):
                overlap.insert(0, previous)
                if estimate_tokens(" ".join(overlap)) >= CHILD_OVERLAP_TOKENS:
                    break
            current = overlap if len(overlap) < len(current) else []

    if current:
        tail = " ".join(current)
        # Fold a runt into the previous group rather than emitting a fragment.
        if groups and estimate_tokens(tail) < CHILD_MIN_TOKENS // 2:
            groups[-1] = f"{groups[-1]} {tail}"
        else:
            groups.append(tail)

    return groups


def chunk_text_section(section: MdSection) -> ChunkSpec | None:
    """Narrative of one section becomes one parent plus sentence-group children."""
    text = section.text.strip()
    if not text:
        return None

    model_tags = resolve_model_tags(section, text)
    parent = ChunkSpec(
        content=text,
        section_path=section.section_path,
        heading=section.heading,
        chunk_type=ChunkType.TEXT,
        is_parent=True,
        keywords=extract_keywords(text, section.section_path),
        model_tags=model_tags,
    )

    for group in _group_sentences(_split_sentences(text)):
        parent.children.append(
            ChunkSpec(
                content=group,
                section_path=section.section_path,
                heading=section.heading,
                chunk_type=ChunkType.TEXT,
                keywords=extract_keywords(group),
                model_tags=model_tags,
            )
        )

    if not parent.children:
        parent.children.append(
            ChunkSpec(
                content=text,
                section_path=section.section_path,
                heading=section.heading,
                chunk_type=ChunkType.TEXT,
                keywords=parent.keywords,
                model_tags=model_tags,
            )
        )
    return parent


def _split_oversized_parent(parent: ChunkSpec) -> list[ChunkSpec]:
    """Split a text parent over PARENT_MAX_TOKENS at paragraph boundaries."""
    if parent.chunk_type == ChunkType.TABLE or parent.token_count <= PARENT_MAX_TOKENS:
        return [parent]

    paragraphs = [p for p in parent.content.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return [parent]

    midpoint = len(paragraphs) // 2
    halves = ["\n\n".join(paragraphs[:midpoint]), "\n\n".join(paragraphs[midpoint:])]
    out: list[ChunkSpec] = []
    for index, half in enumerate(halves, start=1):
        piece = ChunkSpec(
            content=half,
            section_path=f"{parent.section_path} ({index}/{len(halves)})",
            heading=parent.heading,
            chunk_type=parent.chunk_type,
            is_parent=True,
            keywords=extract_keywords(half),
            model_tags=parent.model_tags,
        )
        piece.children = [
            child for child in parent.children if child.content in half
        ] or [
            ChunkSpec(
                content=half,
                section_path=piece.section_path,
                heading=parent.heading,
                chunk_type=parent.chunk_type,
                keywords=piece.keywords,
                model_tags=parent.model_tags,
            )
        ]
        out.append(piece)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_chunks(document: MdDocument) -> list[ChunkSpec]:
    """Chunk a knowledge document into parents, each carrying its children."""
    parents: list[ChunkSpec] = []

    for section in document.sections:
        text_parent = chunk_text_section(section)
        if text_parent is not None:
            parents.extend(_split_oversized_parent(text_parent))
        for table in section.tables:
            parents.append(chunk_table(table, section))

    return parents


def count_chunks(parents: list[ChunkSpec]) -> tuple[int, int]:
    """(parent count, child count)."""
    return len(parents), sum(len(p.children) for p in parents)
