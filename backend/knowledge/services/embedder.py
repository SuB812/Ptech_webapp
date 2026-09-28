"""Chunk persistence and embedding (FR-08, specs/05-rag-pipeline.md section 4).

Only children are embedded. The embedded text is ``section_path + "\\n" + content``
so a row that never names its model still carries ``LT-150`` in its vector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction

from common.enums import ChunkType, DocStatus, KnowledgeKind
from common.llm import CallLog, embed_texts
from common.tables import normalize_cell
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services.chunker import ChunkSpec, build_chunks
from knowledge.services.md_parse import MdDocument, MdSection, MdTable, parse_markdown

logger = logging.getLogger(__name__)


class IndexingError(RuntimeError):
    """Chunking or embedding failed for a knowledge document."""


@dataclass
class IndexResult:
    parents: int
    children: int
    embedded: int

    @property
    def total(self) -> int:
        return self.parents + self.children


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _pdf_to_md_document(path: Path, title: str) -> MdDocument:
    """Adapter so a PDF knowledge document can go through the same chunker.

    Sections become one per page, so ``section_path`` is only ``title > p.N``.
    That is markedly weaker than a Markdown document's real heading path, which
    is why our own reference material is kept as ``.md``: TRAP-3 depends on
    ``4.1 발전 부문`` being in the path, and a PDF page number cannot supply that.
    """
    from documents.services.pdf_extract import extract_pdf

    result = extract_pdf(path)
    sections: list[MdSection] = []
    table_index = 0

    for page in result.pages:
        path_parts = [title, f"p.{page.page_no}"]
        section = MdSection(
            heading=f"p.{page.page_no}",
            level=2,
            heading_path=path_parts,
            text=page.text,
        )
        for table in page.tables:
            section.tables.append(
                MdTable(index=table_index, rows=table.rows, heading_path=list(path_parts))
            )
            table_index += 1
        sections.append(section)

    return MdDocument(title=title, doc_no=result.doc_no, revision_date=None, sections=sections)


def load_document_structure(document: KnowledgeDocument) -> MdDocument:
    """Parse the stored file into the structure the chunker consumes."""
    path = Path(document.file.path)
    suffix = path.suffix.lower()

    if suffix == ".md":
        return parse_markdown(path.read_text(encoding="utf-8"))
    if suffix == ".pdf":
        return _pdf_to_md_document(path, document.title or path.stem)
    raise IndexingError(f"지원하지 않는 형식입니다: {suffix} (.md 또는 .pdf 만 가능)")


def detect_metadata(path: Path) -> dict:
    """Title / doc_no / revision_date read from the file, for upload defaults."""
    if path.suffix.lower() != ".md":
        return {}
    parsed = parse_markdown(path.read_text(encoding="utf-8"))
    return {
        "title": parsed.title,
        "doc_no": parsed.doc_no,
        "revision_date": parsed.revision_date,
    }


def guess_doc_kind(path: Path, text: str = "") -> str:
    """Best-effort kind for the management command; the UI asks explicitly."""
    haystack = f"{path.name} {text[:500]}"
    if "카탈로그" in haystack or "catalog" in haystack.lower():
        return KnowledgeKind.CATALOG
    if any(word in haystack for word in ("인증", "시험", "실적", "성적서")):
        return KnowledgeKind.QA
    return KnowledgeKind.OTHER


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist(document: KnowledgeDocument, parents: list[ChunkSpec]) -> tuple[int, int]:
    rows_parents = 0
    rows_children = 0

    for spec in parents:
        parent = KnowledgeChunk.objects.create(
            document=document,
            is_parent=True,
            content=spec.content,
            section_path=spec.section_path[:300],
            heading=spec.heading[:300],
            chunk_type=spec.chunk_type,
            token_count=spec.token_count,
            keywords=spec.keywords,
            model_tags=spec.model_tags,
            embedding=None,  # parents are never embedded
        )
        rows_parents += 1

        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    document=document,
                    parent=parent,
                    is_parent=False,
                    content=child.content,
                    section_path=child.section_path[:300],
                    heading=child.heading[:300],
                    chunk_type=child.chunk_type,
                    token_count=child.token_count,
                    keywords=child.keywords,
                    model_tags=child.model_tags,
                )
                for child in spec.children
            ]
        )
        rows_children += len(spec.children)

    return rows_parents, rows_children


def _embed_children(document: KnowledgeDocument, log: CallLog | None) -> int:
    children = list(
        document.chunks.filter(is_parent=False).order_by("id")
    )
    if not children:
        return 0

    texts = [
        f"{c.section_path}\n{c.content}" if c.section_path else c.content
        for c in children
    ]
    vectors = embed_texts(texts, log=log)

    if len(vectors) != len(children):
        raise IndexingError(
            f"임베딩 개수 불일치: 청크 {len(children)}개, 벡터 {len(vectors)}개"
        )

    for chunk, vector in zip(children, vectors):
        chunk.embedding = vector
    KnowledgeChunk.objects.bulk_update(children, ["embedding"], batch_size=200)
    return len(children)


def index_document(
    document: KnowledgeDocument, *, log: CallLog | None = None
) -> IndexResult:
    """Chunk, store and embed one knowledge document. Re-indexing is idempotent."""
    document.status = DocStatus.INDEXING
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])

    try:
        structure = load_document_structure(document)
        specs = build_chunks(structure)
        if not specs:
            raise IndexingError("청크를 만들 수 없습니다. 문서가 비어 있는지 확인하세요.")

        with transaction.atomic():
            document.chunks.all().delete()
            parents, children = _persist(document, specs)

        embedded = _embed_children(document, log)

        document.chunk_count = parents + children
        document.embedding_model = settings.EMBEDDING_MODEL
        document.status = DocStatus.INDEXED
        # Fill metadata the caller left blank, so the service is self-sufficient
        # whether it is reached from the API, the management command or a test.
        if structure.title and not document.title:
            document.title = structure.title
        if structure.doc_no and not document.doc_no:
            document.doc_no = structure.doc_no
        if structure.revision_date and not document.revision_date:
            document.revision_date = structure.revision_date
        document.save()

        logger.info(
            "indexed %s: %s parents, %s children, %s embedded",
            document.pk, parents, children, embedded,
        )
        return IndexResult(parents=parents, children=children, embedded=embedded)

    except Exception as exc:
        document.status = DocStatus.FAILED
        document.error_message = str(exc)[:2000]
        document.save(update_fields=["status", "error_message", "updated_at"])
        raise


# ---------------------------------------------------------------------------
# Input-document guard (principle 1)
# ---------------------------------------------------------------------------

_BID_FILENAME_HINTS = ("공고", "사양서", "규격서", "rfp", "입찰")
_BID_CONTENT_HINTS = ("공고번호", "입찰공고", "기술사양서")


def looks_like_bid_document(filename: str, head: str = "") -> bool:
    """Reject announcements and spec sheets from the knowledge base.

    Indexing an input document poisons the next bid's evidence, so this is
    checked on the server as well as in the UI (FR-08). It can produce false
    positives, so the caller's error message tells the user how to proceed.
    """
    name = normalize_cell(filename).lower()
    if any(hint in name for hint in _BID_FILENAME_HINTS):
        return True
    return any(hint in head for hint in _BID_CONTENT_HINTS)
