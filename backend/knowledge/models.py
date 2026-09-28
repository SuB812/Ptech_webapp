"""RAG knowledge base models (specs/03-data-model.md section 4).

These are our own reference materials, and the only things in the system that
get vector-indexed. They have no relation to ``BidProject``: they are a global
resident asset reused by every bid (principle 1).
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from pgvector.django import HnswIndex, VectorField

from common.enums import ChunkType, DocStatus, KnowledgeKind
from common.models import TimeStampedModel


class KnowledgeDocument(TimeStampedModel):
    """One of our own documents (catalogue, certifications/tests/records)."""

    title = models.CharField("제목", max_length=300)
    doc_no = models.CharField("문서번호", max_length=100, blank=True, db_index=True)
    doc_kind = models.CharField("종류", max_length=20, choices=KnowledgeKind.choices)
    file = models.FileField("파일", upload_to="knowledge/")
    revision_date = models.DateField("개정일/기준일", null=True, blank=True)
    status = models.CharField(
        "상태", max_length=20, choices=DocStatus.choices, default=DocStatus.UPLOADED
    )
    chunk_count = models.IntegerField("청크 수", default=0)
    embedding_model = models.CharField("임베딩 모델", max_length=100, blank=True)
    error_message = models.TextField("오류 사유", blank=True)

    class Meta:
        verbose_name = "지식 문서"
        verbose_name_plural = "지식 문서"
        ordering = ["doc_kind", "id"]

    def __str__(self) -> str:
        return f"{self.title} ({self.doc_no})" if self.doc_no else self.title


class KnowledgeChunk(TimeStampedModel):
    """A parent-child chunk (FR-09).

    Search hits children; the LLM receives the parent. A lone
    ``방수·방진 등급: IP65`` line cannot tell the model whether that is LT-150 or
    LT-200, standard or optional -- the whole table can. Embedding the whole
    table instead would blur the vector so a narrow query like ``염수분무``
    stops matching (specs/05-rag-pipeline.md 3.1).

    Only children carry an ``embedding``.
    """

    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    is_parent = models.BooleanField("부모 청크", default=False)

    content = models.TextField("내용")
    section_path = models.CharField("절 경로", max_length=300, blank=True)
    heading = models.CharField("헤딩", max_length=300, blank=True)
    page_no = models.IntegerField("페이지", null=True, blank=True)
    chunk_type = models.CharField(
        "청크 종류", max_length=20, choices=ChunkType.choices, default=ChunkType.TEXT
    )
    token_count = models.IntegerField("토큰 수", default=0)

    embedding = VectorField("임베딩", dimensions=settings.EMBEDDING_DIM, null=True, blank=True)

    keywords = ArrayField(
        models.CharField(max_length=60),
        verbose_name="정확 매칭 토큰",
        default=list,
        blank=True,
    )
    # TRAP-1 defence: which product model this chunk belongs to. An empty list
    # means model-agnostic (common info) and must not be penalised by the
    # retriever's model filter (specs/05-rag-pipeline.md 3.5, 5.3-5).
    model_tags = ArrayField(
        models.CharField(max_length=30),
        verbose_name="제품 모델 태그",
        default=list,
        blank=True,
    )

    class Meta:
        verbose_name = "지식 청크"
        verbose_name_plural = "지식 청크"
        ordering = ["document_id", "id"]
        indexes = [
            # Cosine similarity over child embeddings.
            HnswIndex(
                name="kchunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            # Trigram matching for the keyword half of the hybrid search.
            GinIndex(
                name="kchunk_content_trgm",
                fields=["content"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(name="kchunk_keywords_gin", fields=["keywords"]),
            GinIndex(name="kchunk_model_tags_gin", fields=["model_tags"]),
            models.Index(fields=["document", "is_parent"]),
        ]

    def __str__(self) -> str:
        kind = "부모" if self.is_parent else "자식"
        return f"[{kind}] {self.section_path} :: {self.content[:40]}"
