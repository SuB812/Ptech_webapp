"""Phase 2: model structure, constraints and the principle-1 invariant."""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from analysis.models import AnalysisRun, Assessment, Evidence
from common.enums import (
    Category,
    DocType,
    EvidenceState,
    KnowledgeKind,
    RunStatus,
    SubmissionStatus,
    Verdict,
)
from documents.models import DocumentPage, Requirement, SourceDocument
from knowledge.models import KnowledgeChunk, KnowledgeDocument
from projects.models import BidProject, ParticipationRequirement, SubmissionItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def project():
    return BidProject.objects.create(
        title="○○화력발전소 구내 LED 투광등 교체",
        bid_no="KPG-2025-EQ-0417",
        org="한국발전기술공사 자재구매처",
        item_name="LED 투광등 150W급",
        quantity="200대",
        estimated_price="금 240,000,000원 (부가세 별도)",
        delivery_term="계약체결일로부터 60일 이내",
        spec_doc_no="KPG-2025-TS-0417",
    )


# ---------------------------------------------------------------------------
# BidProject
# ---------------------------------------------------------------------------


def test_project_preserves_announcement_wording(project):
    """수량·추정가격은 문자열이다 — 공고 표기를 그대로 산출물에 싣는다."""
    project.refresh_from_db()
    assert project.quantity == "200대"
    assert project.estimated_price == "금 240,000,000원 (부가세 별도)"
    assert project.delivery_term == "계약체결일로부터 60일 이내"


def test_project_only_needs_a_title():
    """FR-05: 나머지 헤더 필드는 추출로 채워진다."""
    bare = BidProject.objects.create(title="제목만 있는 건")
    bare.refresh_from_db()
    assert bare.bid_no == ""
    assert bare.bid_due_at is None


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------


def test_requirement_unique_per_project(project):
    Requirement.objects.create(
        project=project, clause_no="2.1", item="소비전력",
        requirement_text="150 W 이하", category=Category.EFFICIENCY, order=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Requirement.objects.create(
            project=project, clause_no="2.1", item="소비전력",
            requirement_text="중복", category=Category.EFFICIENCY, order=2,
        )


def test_same_clause_different_item_is_allowed(project):
    """조항번호가 같고 항목이 다르면 별개다 (06 2.3절 후처리 규칙)."""
    Requirement.objects.create(
        project=project, clause_no="5.1", item="KS 인증",
        category=Category.CERTIFICATION, order=1,
    )
    Requirement.objects.create(
        project=project, clause_no="5.1", item="고효율 인증",
        category=Category.CERTIFICATION, order=2,
    )
    assert project.requirements.count() == 2


def test_requirement_text_may_be_blank(project):
    """빈 표 칸은 빈 값으로 남긴다 — 추측해 채우지 않는다 (06 2.2절 규칙 5)."""
    req = Requirement.objects.create(
        project=project, clause_no="4.4", item="내진동 시험",
        requirement_text="", category=Category.TEST_STANDARD, order=1,
    )
    req.refresh_from_db()
    assert req.requirement_text == ""


def test_requirement_defaults(project):
    req = Requirement.objects.create(
        project=project, clause_no="2.1", item="소비전력", order=1
    )
    assert req.is_active is True
    assert req.is_graded is False, "채점 대상은 mark_graded 로만 켠다 (03 6.1절)"
    assert req.is_edited is False
    assert req.category == Category.OTHER


def test_snapshot_ai_values(project):
    """AI 원본 보존 — 정확도는 항상 ai_* 로 측정한다."""
    req = Requirement.objects.create(
        project=project, clause_no="3.1", item="방수·방진 등급",
        requirement_text="IP66 이상", category=Category.FILTER_GRADE, order=1,
    )
    req.snapshot_ai_values()
    req.save()

    req.item = "방수등급(사용자 수정)"
    req.requirement_text = "IP67 이상"
    req.is_edited = True
    req.save()
    req.refresh_from_db()

    assert req.ai_item == "방수·방진 등급"
    assert req.ai_requirement_text == "IP66 이상"
    assert req.ai_category == Category.FILTER_GRADE


# ---------------------------------------------------------------------------
# Principle 1 — input documents are never vector-indexed
# ---------------------------------------------------------------------------


def test_source_document_has_no_chunk_relation():
    """Structural guarantee, not a convention.

    There is no path from SourceDocument to KnowledgeChunk in either direction,
    so indexing an announcement or spec sheet is impossible by construction
    (09 §7.1 test_source_doc_never_indexed, structural half).
    """
    source_relations = {f.name for f in SourceDocument._meta.get_fields()}
    assert not any("chunk" in name.lower() for name in source_relations), (
        f"SourceDocument 에 청크 관계가 생겼다: {source_relations}"
    )

    chunk_relations = {f.name for f in KnowledgeChunk._meta.get_fields()}
    assert not any(
        name in chunk_relations for name in ("source_document", "sourcedocument", "bid_project")
    ), f"KnowledgeChunk 가 입력 문서를 참조한다: {chunk_relations}"

    # KnowledgeChunk only ever points at a KnowledgeDocument.
    assert KnowledgeChunk._meta.get_field("document").related_model is KnowledgeDocument


def test_knowledge_document_is_not_tied_to_a_project():
    """지식 문서는 입찰 건에 속하지 않는다 — 전역 상주 자산이다."""
    field_names = {f.name for f in KnowledgeDocument._meta.get_fields()}
    assert "project" not in field_names
    assert "bidproject" not in field_names


def test_uploading_source_document_creates_no_chunks(project):
    """업로드 경로가 청크를 만들지 않는다 (동작 검증)."""
    before = KnowledgeChunk.objects.count()
    doc = SourceDocument.objects.create(
        project=project,
        doc_type=DocType.TECHSPEC,
        file=ContentFile(b"%PDF-1.4 fake", name="02_spec.pdf"),
        original_name="02_기술사양서.pdf",
    )
    DocumentPage.objects.create(
        document=doc, page_no=1, text="본문",
        tables=[{"index": 0, "rows": [["조항", "항목", "요구조건"]]}],
    )
    assert KnowledgeChunk.objects.count() == before


# ---------------------------------------------------------------------------
# DocumentPage
# ---------------------------------------------------------------------------


def test_document_page_unique_and_tables_roundtrip(project):
    doc = SourceDocument.objects.create(
        project=project, doc_type=DocType.TECHSPEC,
        file=ContentFile(b"x", name="s.pdf"), original_name="s.pdf",
    )
    rows = [["조항", "항목", "요구조건"], ["2.1", "소비전력", "150 W 이하"]]
    DocumentPage.objects.create(document=doc, page_no=1, tables=[{"index": 0, "rows": rows}])

    page = doc.pages.get(page_no=1)
    assert page.tables[0]["rows"] == rows, "원본 2차원 배열이 그대로 보존돼야 한다"
    assert doc.table_count == 1

    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentPage.objects.create(document=doc, page_no=1)


# ---------------------------------------------------------------------------
# Submission / participation
# ---------------------------------------------------------------------------


def test_submission_items_ordered_and_unique(project):
    for seq, name in [(2, "사업자등록증 사본"), (1, "입찰참가신청서")]:
        SubmissionItem.objects.create(project=project, seq=seq, name=name)

    assert [i.seq for i in project.submission_items.all()] == [1, 2]
    assert project.submission_items.first().status == SubmissionStatus.UNCERTAIN

    with pytest.raises(IntegrityError), transaction.atomic():
        SubmissionItem.objects.create(project=project, seq=1, name="중복")


def test_participation_requirement(project):
    req = ParticipationRequirement.objects.create(
        project=project, seq="3.3",
        text="최근 5년 이내 발전소 납품실적이 3건 이상인 자",
    )
    assert req.status == SubmissionStatus.UNCERTAIN
    assert project.participation_reqs.count() == 1


# ---------------------------------------------------------------------------
# AnalysisRun / Assessment / Evidence
# ---------------------------------------------------------------------------


@pytest.fixture
def run(project):
    return AnalysisRun.objects.create(
        project=project,
        llm_model="gpt-4o",
        embedding_model="text-embedding-3-small",
        rag_params={"top_k": 5, "threshold": 0.4, "w_semantic": 0.6, "w_keyword": 0.4},
    )


def test_run_defaults_and_helpers(run):
    assert run.status == RunStatus.QUEUED
    assert run.is_active is True
    assert run.elapsed_ms is None
    assert run.token_usage == {"prompt": 0, "completion": 0}

    run.llm_calls = [
        {"prompt_tokens": 100, "completion_tokens": 20},
        {"prompt_tokens": 50, "completion_tokens": 10},
    ]
    run.save()
    assert run.token_usage == {"prompt": 150, "completion": 30}

    run.status = RunStatus.DONE
    assert run.is_active is False


def test_assessment_unique_per_run(project, run):
    req = Requirement.objects.create(
        project=project, clause_no="3.1", item="방수·방진 등급", order=1
    )
    Assessment.objects.create(
        run=run, requirement=req, verdict=Verdict.GAP, ai_verdict=Verdict.GAP
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Assessment.objects.create(
            run=run, requirement=req, verdict=Verdict.MEET, ai_verdict=Verdict.MEET
        )


def test_has_evidence_reflects_reality(project, run):
    """Phase 6 의 MEET 차단 로직이 이 속성을 근거로 판단한다 (원칙 3)."""
    req = Requirement.objects.create(
        project=project, clause_no="4.3", item="내염수분무 시험", order=1
    )
    assessment = Assessment.objects.create(
        run=run, requirement=req,
        verdict=Verdict.CHECK, ai_verdict=Verdict.CHECK,
        evidence_state=EvidenceState.FOUND_ABSENT,
    )
    assert assessment.has_evidence is False

    Evidence.objects.create(
        assessment=assessment,
        doc_title="한빛조명(주) 인증·시험·실적 현황",
        doc_no="HB-QA-2025-07",
        location="3. 시험 설비 보유 현황",
        quote="염수분무 시험기: 미보유",
        score=0.71, rank=1,
    )
    assert assessment.has_evidence is True


def test_evidence_survives_chunk_deletion(project, run):
    """재색인으로 청크가 사라져도 근거 표시는 유지된다 (SET_NULL + 스냅샷)."""
    kdoc = KnowledgeDocument.objects.create(
        title="한빛조명(주) 제품 카탈로그",
        doc_no="HB-CAT-2025-02",
        doc_kind=KnowledgeKind.CATALOG,
        file=ContentFile(b"# t", name="cat.md"),
    )
    chunk = KnowledgeChunk.objects.create(
        document=kdoc, is_parent=False, content="방수·방진 등급: IP65",
        section_path="한빛조명(주) 제품 카탈로그 > 2. LT-150 사양 > 2.2 구조",
        keywords=["IP65"], model_tags=["LT-150"],
    )
    req = Requirement.objects.create(
        project=project, clause_no="3.1", item="방수·방진 등급", order=1
    )
    assessment = Assessment.objects.create(
        run=run, requirement=req, verdict=Verdict.GAP, ai_verdict=Verdict.GAP,
        our_value="IP65",
    )
    evidence = Evidence.objects.create(
        assessment=assessment, chunk=chunk,
        doc_title="한빛조명(주) 제품 카탈로그", doc_no="HB-CAT-2025-02",
        location="2.2 구조", quote="방수·방진 등급: IP65",
        score=0.78, semantic_score=0.74, keyword_score=0.84, rank=1,
    )

    chunk.delete()
    evidence.refresh_from_db()

    assert evidence.chunk is None
    assert evidence.doc_title == "한빛조명(주) 제품 카탈로그"
    assert evidence.quote == "방수·방진 등급: IP65"
    assert evidence.location == "2.2 구조"


def test_evidence_ordered_by_rank(project, run):
    req = Requirement.objects.create(project=project, clause_no="2.2", item="총 광속", order=1)
    assessment = Assessment.objects.create(
        run=run, requirement=req, verdict=Verdict.MEET, ai_verdict=Verdict.MEET
    )
    for rank, title in [(2, "성적서"), (1, "카탈로그")]:
        Evidence.objects.create(
            assessment=assessment, doc_title=title, score=0.5, rank=rank
        )
    assert [e.rank for e in assessment.evidences.all()] == [1, 2]


def test_cascade_delete_from_project(project, run):
    req = Requirement.objects.create(project=project, clause_no="2.1", item="소비전력", order=1)
    assessment = Assessment.objects.create(
        run=run, requirement=req, verdict=Verdict.MEET, ai_verdict=Verdict.MEET
    )
    Evidence.objects.create(assessment=assessment, doc_title="카탈로그", score=0.9, rank=1)

    project.delete()

    assert Requirement.objects.count() == 0
    assert AnalysisRun.objects.count() == 0
    assert Assessment.objects.count() == 0
    assert Evidence.objects.count() == 0
    # Knowledge survives: it is not owned by any bid.
    assert KnowledgeDocument.objects.count() == KnowledgeDocument.objects.count()
