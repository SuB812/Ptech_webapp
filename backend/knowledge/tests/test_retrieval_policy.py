"""Phase 4: per-requirement retrieval policy (specs/05-rag-pipeline.md 5.5).

Documents the two measured refinements to specs/06 section 3.1:

* the semantic query is the item name alone, not item + requirement_text;
* the model filter is skipped for categories where the model is irrelevant.

Both were driven by measurement, not taste -- the composed query lost the
evidence for clauses 4.3 and 4.4 completely, and model-filtering the delivery
records would have reduced the count from 2 to 1, which 09 TRAP-3 names as an
error in its own right.
"""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile

from common.enums import Category, ChunkType, KnowledgeKind
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services import retriever
from knowledge.services.keywords import build_item_probes

pytestmark = pytest.mark.django_db


def test_prefix_variants_generated():
    """KS 시험명의 `내~` 접두사를 벗긴 형태도 프로브에 들어간다."""
    assert build_item_probes("내진동 시험") == ["내진동 시험", "진동 시험"]
    assert build_item_probes("내염수분무 시험") == ["내염수분무 시험", "염수분무 시험"]
    # 접두사가 아닌 항목은 그대로.
    assert build_item_probes("소비전력") == ["소비전력"]
    assert build_item_probes("본체 무게") == ["본체 무게"]
    assert build_item_probes("") == []


@pytest.fixture
def records():
    qa = KnowledgeDocument.objects.create(
        title="한빛조명(주) 인증·시험·실적 현황",
        doc_no="HB-QA-2025-07",
        doc_kind=KnowledgeKind.QA,
        file=ContentFile(b"# q", name="q.md"),
    )
    parent = KnowledgeChunk.objects.create(
        document=qa, is_parent=True, chunk_type=ChunkType.TABLE,
        content="| 계약연도 | 발주처 | 품목 |\n|---|---|---|\n"
                "| 2022 | 한국남부발전 | LT-150 |\n| 2024 | 한국서부발전 | LT-200 |",
        section_path="한빛조명(주) 인증·시험·실적 현황 > 4. 최근 5년 납품실적 > 4.1 발전 부문",
    )
    made = {}
    for year, org, model in [("2022", "한국남부발전", "LT-150"), ("2024", "한국서부발전", "LT-200")]:
        made[org] = KnowledgeChunk.objects.create(
            document=qa, parent=parent, is_parent=False, chunk_type=ChunkType.TABLE_ROW,
            content=f"4.1 발전 부문 — 계약연도: {year}, 발주처: {org}, 품목: {model}",
            section_path=parent.section_path,
            keywords=[], model_tags=[model],
            embedding=[0.0] * 1536,
        )
    return made


def test_track_record_is_not_model_filtered(records):
    """TRAP-3: 품목 모델은 실적 인정 조건이 아니다.

    LT-150 필터를 걸면 2024 서부발전(LT-200) 레코드가 감점되어 사라지고,
    LLM 이 "1건" 이라고 판정한다. 09 TRAP-3 이 명시한 오답이다.
    """
    filtered = retriever.retrieve_for_requirement(
        item="납품실적",
        requirement_text="최근 5년 발전소 납품실적 3건 이상",
        category=Category.TRACK_RECORD,
        model_hint="LT-150",
        threshold=0.0,
        top_k=10,
    )
    contents = " ".join(h.chunk.content for h in filtered)
    assert "한국남부발전" in contents
    assert "한국서부발전" in contents, "LT-200 실적이 모델 필터로 사라졌다"

    by_id = {h.chunk.id: h for h in filtered}
    lt150 = by_id[records["한국남부발전"].id].score
    lt200 = by_id[records["한국서부발전"].id].score
    assert lt200 == pytest.approx(lt150, rel=0.2), (
        "실적 항목에서는 모델에 따라 점수가 갈리면 안 된다"
    )


def test_dimension_category_is_model_filtered(records):
    """반대로 치수·성능 항목은 모델로 걸러야 한다 (TRAP-1)."""
    hits = retriever.retrieve_for_requirement(
        item="발주처",
        requirement_text="",
        category=Category.DIMENSION,
        model_hint="LT-150",
        threshold=0.0,
        top_k=10,
    )
    by_id = {h.chunk.id: h for h in hits}
    assert by_id[records["한국남부발전"].id].score > by_id[records["한국서부발전"].id].score


def test_certification_is_exempt():
    assert Category.CERTIFICATION in retriever.MODEL_FILTER_EXEMPT_CATEGORIES
    assert Category.TRACK_RECORD in retriever.MODEL_FILTER_EXEMPT_CATEGORIES
    assert Category.EFFICIENCY not in retriever.MODEL_FILTER_EXEMPT_CATEGORIES
    assert Category.DIMENSION not in retriever.MODEL_FILTER_EXEMPT_CATEGORIES


def test_empty_item_returns_nothing(records):
    assert retriever.retrieve_for_requirement(item="", requirement_text="x") == []
