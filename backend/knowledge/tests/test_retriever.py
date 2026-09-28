"""Phase 4: hybrid retrieval.

Runs under LLM_FAKE, where embeddings are deterministic pseudo-vectors. Random
unit vectors are near-orthogonal, so the semantic score is ~0 for everything and
only the keyword half is meaningful here (specs/02-architecture.md 5.1). These
tests therefore pass ``threshold=0.0`` and assert on ``keyword_score`` ordering.
Semantic ranking quality is measured separately with a real key.
"""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile

from common.enums import ChunkType, KnowledgeKind
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from knowledge.services import retriever

pytestmark = pytest.mark.django_db


@pytest.fixture
def corpus():
    """A miniature stand-in for the two sample documents."""
    doc = KnowledgeDocument.objects.create(
        title="한빛조명(주) 제품 카탈로그",
        doc_no="HB-CAT-2025-02",
        doc_kind=KnowledgeKind.CATALOG,
        file=ContentFile(b"# c", name="c.md"),
    )
    qa = KnowledgeDocument.objects.create(
        title="한빛조명(주) 인증·시험·실적 현황",
        doc_no="HB-QA-2025-07",
        doc_kind=KnowledgeKind.QA,
        file=ContentFile(b"# q", name="q.md"),
    )

    def add(document, content, path, keywords, model_tags, parent=None):
        return KnowledgeChunk.objects.create(
            document=document,
            parent=parent,
            is_parent=parent is None and keywords is None,
            content=content,
            section_path=path,
            chunk_type=ChunkType.TABLE_ROW,
            keywords=keywords or [],
            model_tags=model_tags,
            embedding=[0.0] * 1536 if keywords is not None else None,
        )

    made = {}
    made["ip65"] = add(
        doc, "2.2 구조 — 항목: 방수·방진 등급, 사양: IP65",
        "한빛조명(주) 제품 카탈로그 > 2. LT-150 사양 > 2.2 구조",
        ["IP65"], ["LT-150"],
    )
    made["ip66"] = add(
        doc, "2.3 선택사양 — 사양명: IP66 강화 하우징, 영향: 무게 +1.4kg, 납기 +3주",
        "한빛조명(주) 제품 카탈로그 > 2. LT-150 사양 > 2.3 선택사양",
        ["IP66", "1.4KG", "3주"], ["LT-150"],
    )
    made["lt150_power"] = add(
        doc, "2.1 성능 — 항목: 소비전력, 사양: 140 W",
        "한빛조명(주) 제품 카탈로그 > 2. LT-150 사양 > 2.1 성능",
        ["140W"], ["LT-150"],
    )
    made["lt200_power"] = add(
        doc, "3.1 성능 — 항목: 소비전력, 사양: 195 W",
        "한빛조명(주) 제품 카탈로그 > 3. LT-200 사양 > 3.1 성능",
        ["195W"], ["LT-200"],
    )
    made["warranty"] = add(
        doc, "납품일로부터 2년간 무상 보증한다.",
        "한빛조명(주) 제품 카탈로그 > 4. 공급 조건 > 4.2 보증",
        ["2년"], [],
    )
    made["salt"] = add(
        qa, "3. 시험 설비 보유 현황 — 설비명: 염수분무 시험기, 보유 여부: 미보유",
        "한빛조명(주) 인증·시험·실적 현황 > 3. 시험 설비 보유 현황",
        [], [],
    )
    made["vibration"] = add(
        qa, "3. 시험 설비 보유 현황 — 설비명: 진동 시험기, 보유 여부: 미보유",
        "한빛조명(주) 인증·시험·실적 현황 > 3. 시험 설비 보유 현황",
        [], [],
    )
    made["power_record"] = add(
        qa, "4.1 발전 부문 — 계약연도: 2022, 발주처: 한국남부발전, 품목: LT-150",
        "한빛조명(주) 인증·시험·실적 현황 > 4. 최근 5년 납품실적 > 4.1 발전 부문",
        [], ["LT-150"],
    )
    return made


def scores(hits):
    return {h.chunk.id: h for h in hits}


# ---------------------------------------------------------------------------
# Keyword exactness — 09 §7.1 test_retriever_keyword_exact
# ---------------------------------------------------------------------------


def test_ip66_query_prefers_ip66_over_ip65(corpus):
    """한 글자 차이가 판정을 뒤집는다. 의미 검색만으로는 갈리지 않는다."""
    hits = retriever.search("IP66 이상", threshold=0.0, top_k=10)
    found = scores(hits)

    ip66 = found[corpus["ip66"].id]
    ip65 = found[corpus["ip65"].id]

    assert ip66.keyword_score == 1.0, "IP66 정확 매칭이 1.0 이어야 한다"
    assert ip66.keyword_score > ip65.keyword_score
    assert ip66.score > ip65.score
    assert ip66.rank < ip65.rank


def test_ip65_query_prefers_ip65(corpus):
    hits = retriever.search("IP65", threshold=0.0, top_k=10)
    found = scores(hits)
    assert found[corpus["ip65"].id].keyword_score == 1.0
    assert found[corpus["ip66"].id].keyword_score < 1.0


def test_exact_numeric_token_matches(corpus):
    """`8 kg 이하` 요구조건과 `7.2 kg` 자사값은 다른 토큰이다."""
    hits = retriever.search("소비전력 140 W", threshold=0.0, top_k=10)
    found = scores(hits)
    assert found[corpus["lt150_power"].id].keyword_score == 1.0
    assert found[corpus["lt200_power"].id].keyword_score < 1.0


# ---------------------------------------------------------------------------
# Model filter — 09 §7.1 test_retriever_model_filter, TRAP-1
# ---------------------------------------------------------------------------


def test_model_filter_demotes_the_other_model(corpus):
    """LT-150 요구에 LT-200 근거가 올라오는 것을 막는다."""
    unfiltered = scores(retriever.search("소비전력", threshold=0.0, top_k=20))
    filtered = scores(
        retriever.search("소비전력", threshold=0.0, top_k=20, model_filter="LT-150")
    )

    lt200_before = unfiltered[corpus["lt200_power"].id].score
    lt200_after = filtered[corpus["lt200_power"].id].score
    lt150_after = filtered[corpus["lt150_power"].id].score

    assert lt200_after < lt200_before, "LT-200 청크가 감점되지 않았다"
    assert lt200_after == pytest.approx(lt200_before * 0.3, rel=0.05)
    assert lt150_after > lt200_after
    assert filtered[corpus["lt150_power"].id].rank < filtered[corpus["lt200_power"].id].rank


def test_model_filter_never_drops_untagged_chunks(corpus):
    """빈 model_tags 는 공통 정보다. 감점하면 보증·납기 근거가 사라진다."""
    unfiltered = scores(retriever.search("보증 2년", threshold=0.0, top_k=20))
    filtered = scores(
        retriever.search("보증 2년", threshold=0.0, top_k=20, model_filter="LT-150")
    )
    warranty = corpus["warranty"].id
    assert filtered[warranty].score == pytest.approx(unfiltered[warranty].score)


def test_matching_model_gets_a_bonus(corpus):
    unfiltered = scores(retriever.search("소비전력", threshold=0.0, top_k=20))
    filtered = scores(
        retriever.search("소비전력", threshold=0.0, top_k=20, model_filter="LT-150")
    )
    before = unfiltered[corpus["lt150_power"].id].score
    after = filtered[corpus["lt150_power"].id].score
    assert after == pytest.approx(before + 0.1, abs=1e-6)


def test_model_in_query_is_promoted_to_a_filter(corpus):
    """쿼리에 모델명이 하나 있으면 필터로 승격된다."""
    hits = scores(retriever.search("LT-150 소비전력", threshold=0.0, top_k=20))
    assert hits[corpus["lt150_power"].id].score > hits[corpus["lt200_power"].id].score


def test_model_token_does_not_saturate_keyword_scores(corpus):
    """모델 코드는 검색어가 아니라 필터다.

    정확 매칭 토큰에 남겨두면 해당 모델의 모든 청크가 1.0 을 받아 순위가 뭉개진다.
    실제로 조항 5.4 에서 성적서 메타 청크가 납품실적 행보다 위로 올라왔다.
    """
    hits = scores(retriever.search("LT-150 소비전력", threshold=0.0, top_k=20))
    saturated = [h for h in hits.values() if h.keyword_score == 1.0]
    assert len(saturated) <= 1, (
        "모델명만으로 여러 청크가 1.0 을 받았다: "
        f"{[(h.chunk.content[:30], h.keyword_score) for h in saturated]}"
    )


# ---------------------------------------------------------------------------
# TRAP-4 prerequisite — reachable through the keyword path alone
# ---------------------------------------------------------------------------


def test_salt_spray_is_found_without_semantics(corpus):
    """`염수분무 시험` 이 설비 미보유 행을 찾아낸다.

    가짜 임베딩이라 의미 점수가 0 인 상태에서도 키워드 경로만으로 상위에 온다.
    이것이 조항 4.3 을 `found_absent` 로 만들 수 있는 유일한 근거다.
    """
    hits = retriever.search("염수분무 시험", threshold=0.0, top_k=5)
    assert hits, "0건이면 TRAP-4 는 도달 불가다"
    assert hits[0].chunk.id == corpus["salt"].id, [h.chunk.content for h in hits]
    assert hits[0].keyword_score > 0.5
    assert "미보유" in hits[0].chunk.content


def test_both_missing_equipment_rows_are_retrievable(corpus):
    """진동·염수분무 두 행이 모두 검색된다.

    두 행은 `... — 설비명: X 시험기, 보유 여부: 미보유` 로 문자열이 거의 같아
    트라이그램만으로는 서로 구분되지 않는다. 어느 쪽이 1위인지는 의미 점수가
    가르는데, LLM_FAKE 에서는 의미 점수가 0 이므로 여기서는 순위를 단정하지 않는다.
    LLM 에는 어차피 같은 부모(설비 현황표 전체)가 전달되므로 판정에는 영향이 없다.
    실제 임베딩에서의 순위는 `pytest -m llm` 쪽에서 확인한다.
    """
    hits = retriever.search("내진동 시험", threshold=0.0, top_k=10)
    ids = {h.chunk.id for h in hits}
    assert corpus["vibration"].id in ids
    assert corpus["salt"].id in ids

    found = scores(hits)
    assert found[corpus["vibration"].id].keyword_score > 0.3
    # 두 행은 같은 절이므로 같은 부모로 수렴한다.
    assert (
        corpus["vibration"].section_path == corpus["salt"].section_path
    )


def test_section_path_participates_in_matching(corpus):
    """행 내용에 없고 경로에만 있는 말도 찾아야 한다.

    납품실적 행은 '납품실적' 이라는 단어를 담지 않는다. 경로만 담는다.
    내용만 매칭하면 조항 5.4 의 근거를 통째로 놓친다.
    """
    hits = retriever.search("최근 5년 납품실적", threshold=0.0, top_k=10)
    ids = [h.chunk.id for h in hits]
    assert corpus["power_record"].id in ids
    record_hit = scores(hits)[corpus["power_record"].id]
    assert record_hit.keyword_score > 0.3, record_hit.keyword_score


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_zero_hits_is_a_valid_answer(corpus):
    """임계값을 낮춰 억지로 채우지 않는다. 0건은 CHECK 로 이어져야 한다 (원칙 3)."""
    assert retriever.search("완전히 무관한 우주선 추진 방식", threshold=0.95) == []


def test_empty_query_returns_nothing(corpus):
    assert retriever.search("   ") == []


def test_top_k_and_threshold_respected(corpus):
    assert len(retriever.search("시험", threshold=0.0, top_k=2)) <= 2
    high = retriever.search("시험", threshold=0.99, top_k=10)
    assert all(h.score >= 0.99 for h in high)


def test_only_children_are_searched(corpus):
    """부모 청크는 검색 결과로 나오지 않는다."""
    hits = retriever.search("IP65", threshold=0.0, top_k=20)
    assert all(not h.chunk.is_parent for h in hits)


def test_ranks_are_sequential(corpus):
    hits = retriever.search("시험", threshold=0.0, top_k=5)
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


def test_hit_exposes_display_fields(corpus):
    hits = retriever.search("IP65", threshold=0.0, top_k=1)
    hit = hits[0]
    assert hit.doc_title == "한빛조명(주) 제품 카탈로그"
    assert hit.doc_no == "HB-CAT-2025-02"
    assert hit.location == "2. LT-150 사양 2.2 구조", hit.location


def test_doc_kind_filter(corpus):
    hits = retriever.search("시험", threshold=0.0, top_k=20, doc_kinds=["qa"])
    assert hits
    assert all(h.chunk.document.doc_kind == "qa" for h in hits)


def test_unique_parents_deduplicates(corpus):
    """같은 표의 자식이 여러 건 걸리면 부모는 한 번만 전달한다."""
    parent = KnowledgeChunk.objects.create(
        document=corpus["salt"].document,
        is_parent=True,
        content="| 설비명 | 보유 여부 |\n|---|---|\n| 염수분무 시험기 | 미보유 |",
        section_path=corpus["salt"].section_path,
        chunk_type=ChunkType.TABLE,
    )
    KnowledgeChunk.objects.filter(
        id__in=[corpus["salt"].id, corpus["vibration"].id]
    ).update(parent=parent)

    hits = retriever.search("시험기 미보유", threshold=0.0, top_k=10)
    parents = retriever.unique_parents(hits)
    assert len(parents) == len({p.id for p in parents})
    assert parent.id in {p.id for p in parents}
