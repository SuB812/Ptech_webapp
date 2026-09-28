"""Phase 2: KnowledgeChunk storage, vector column and indexes."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection

from common.enums import ChunkType, KnowledgeKind
from knowledge.models import KnowledgeChunk, KnowledgeDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog():
    return KnowledgeDocument.objects.create(
        title="한빛조명(주) 제품 카탈로그",
        doc_no="HB-CAT-2025-02",
        doc_kind=KnowledgeKind.CATALOG,
        file=ContentFile(b"# catalog", name="cat.md"),
    )


def test_parent_child_relation(catalog):
    """표 1개 = 부모 1개, 행 1개 = 자식 1개 (05 3.2절)."""
    parent = KnowledgeChunk.objects.create(
        document=catalog, is_parent=True, chunk_type=ChunkType.TABLE,
        content="| 항목 | 사양 |\n|---|---|\n| 방수·방진 등급 | IP65 |",
        section_path="한빛조명(주) 제품 카탈로그 > 2. LT-150 사양 > 2.2 구조",
        heading="2.2 구조",
    )
    child = KnowledgeChunk.objects.create(
        document=catalog, parent=parent, is_parent=False,
        chunk_type=ChunkType.TABLE_ROW,
        content="LT-150 구조 — 방수·방진 등급: IP65",
        section_path=parent.section_path,
        keywords=["IP65"], model_tags=["LT-150"],
    )

    assert child.parent == parent
    assert list(parent.children.all()) == [child]
    assert parent.parent is None


def test_only_children_carry_embeddings(catalog):
    """부모는 embedding=null 이다 — 표 전체를 임베딩하면 벡터가 뭉개진다."""
    parent = KnowledgeChunk.objects.create(
        document=catalog, is_parent=True, content="표 전체", embedding=None
    )
    child = KnowledgeChunk.objects.create(
        document=catalog, parent=parent, is_parent=False, content="행 하나",
        embedding=[0.0] * settings.EMBEDDING_DIM,
    )
    parent.refresh_from_db()
    child.refresh_from_db()

    assert parent.embedding is None
    assert child.embedding is not None
    assert len(child.embedding) == settings.EMBEDDING_DIM


def test_embedding_dimension_matches_settings(catalog):
    """1536 차원 벡터가 저장·복원된다."""
    vector = [0.01 * i for i in range(settings.EMBEDDING_DIM)]
    chunk = KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="c", embedding=vector
    )
    chunk.refresh_from_db()
    assert len(chunk.embedding) == 1536
    assert pytest.approx(float(chunk.embedding[5]), abs=1e-6) == 0.05


def test_cosine_distance_query_works(catalog):
    """pgvector 연산자가 ORM 을 통해 동작한다 (Phase 4 검색의 전제)."""
    from pgvector.django import CosineDistance

    a = [1.0] + [0.0] * (settings.EMBEDDING_DIM - 1)
    b = [0.0, 1.0] + [0.0] * (settings.EMBEDDING_DIM - 2)
    KnowledgeChunk.objects.create(document=catalog, is_parent=False, content="A", embedding=a)
    KnowledgeChunk.objects.create(document=catalog, is_parent=False, content="B", embedding=b)

    nearest = (
        KnowledgeChunk.objects.filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", a))
        .order_by("distance")
        .first()
    )
    assert nearest.content == "A"


def test_array_fields_roundtrip(catalog):
    chunk = KnowledgeChunk.objects.create(
        document=catalog, is_parent=False,
        content="LT-150 성적서 HB-T-2024-011",
        keywords=["LT-150", "HB-T-2024-011", "IP65"],
        model_tags=["LT-150"],
    )
    chunk.refresh_from_db()
    assert chunk.keywords == ["LT-150", "HB-T-2024-011", "IP65"]
    assert chunk.model_tags == ["LT-150"]


def test_empty_model_tags_means_common(catalog):
    """빈 model_tags 는 '모델 무관' 이다. 검색 시 감점 대상이 아니다 (05 5.3-5)."""
    chunk = KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="납기: 계약 후 45일"
    )
    chunk.refresh_from_db()
    assert chunk.model_tags == []
    assert chunk.keywords == []


def test_array_overlap_lookup(catalog):
    """`keywords && ARRAY[...]` — 하이브리드 검색의 정확 매칭 경로."""
    KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="IP65", keywords=["IP65"]
    )
    KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="IP66", keywords=["IP66"]
    )

    hits = KnowledgeChunk.objects.filter(keywords__overlap=["IP66"])
    assert [c.content for c in hits] == ["IP66"], "IP66 과 IP65 가 갈려야 한다"


def test_model_tag_filter_lookup(catalog):
    """TRAP-1 방어의 DB 측 전제: 모델별로 청크를 가릴 수 있다."""
    KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="140 W", model_tags=["LT-150"]
    )
    KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="195 W", model_tags=["LT-200"]
    )
    KnowledgeChunk.objects.create(
        document=catalog, is_parent=False, content="45일", model_tags=[]
    )

    lt200_only = KnowledgeChunk.objects.filter(model_tags__contains=["LT-200"]).exclude(
        model_tags__contains=["LT-150"]
    )
    assert [c.content for c in lt200_only] == ["195 W"]

    common = KnowledgeChunk.objects.filter(model_tags=[])
    assert [c.content for c in common] == ["45일"]


def test_deleting_document_deletes_chunks(catalog):
    parent = KnowledgeChunk.objects.create(document=catalog, is_parent=True, content="p")
    KnowledgeChunk.objects.create(document=catalog, parent=parent, is_parent=False, content="c")
    assert KnowledgeChunk.objects.count() == 2

    catalog.delete()
    assert KnowledgeChunk.objects.count() == 0


# ---------------------------------------------------------------------------
# Database objects
# ---------------------------------------------------------------------------


def test_required_extensions_installed():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')"
        )
        names = {row[0] for row in cursor.fetchall()}
    assert names == {"vector", "pg_trgm"}


def test_all_four_chunk_indexes_created():
    """HNSW + GIN 3개 (03-data-model.md 4절)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'knowledge_knowledgechunk'"
        )
        indexes = dict(cursor.fetchall())

    assert "kchunk_embedding_hnsw" in indexes
    assert "hnsw" in indexes["kchunk_embedding_hnsw"].lower()
    assert "vector_cosine_ops" in indexes["kchunk_embedding_hnsw"]

    assert "kchunk_content_trgm" in indexes
    assert "gin_trgm_ops" in indexes["kchunk_content_trgm"]

    assert "kchunk_keywords_gin" in indexes
    assert "gin" in indexes["kchunk_keywords_gin"].lower()

    assert "kchunk_model_tags_gin" in indexes
    assert "gin" in indexes["kchunk_model_tags_gin"].lower()
