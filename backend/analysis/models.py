"""Analysis run, verdict, evidence and deliverable models.

specs/03-data-model.md section 5.
"""

from django.db import models

from common.enums import (
    EvidenceState,
    ExportKind,
    InquirySource,
    IssueKind,
    RunStatus,
    Severity,
    Verdict,
)
from common.models import TimeStampedModel
from documents.models import Requirement
from knowledge.models import KnowledgeChunk
from projects.models import BidProject


class AnalysisRun(TimeStampedModel):
    """One end-to-end pipeline execution (FR-23).

    ``prompt_versions`` stores a hash per prompt file. "Change the prompt and
    re-measure" is the core loop of this PoC; without knowing which prompt
    produced which score there is no way to say whether it improved.
    """

    project = models.ForeignKey(
        BidProject, on_delete=models.CASCADE, related_name="runs"
    )
    status = models.CharField(
        "상태", max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED
    )
    current_step = models.CharField("진행 단계", max_length=100, blank=True)
    total_count = models.IntegerField("전체 항목 수", default=0)
    processed_count = models.IntegerField("처리한 항목 수", default=0)

    llm_model = models.CharField("LLM 모델", max_length=100, blank=True)
    embedding_model = models.CharField("임베딩 모델", max_length=100, blank=True)
    rag_params = models.JSONField("RAG 파라미터", default=dict)
    prompt_versions = models.JSONField("프롬프트 버전", default=dict)
    llm_calls = models.JSONField("LLM 호출 기록", default=list)

    started_at = models.DateTimeField("시작", null=True, blank=True)
    finished_at = models.DateTimeField("종료", null=True, blank=True)
    error_message = models.TextField("오류 사유", blank=True)

    summary = models.JSONField("판정 요약", default=dict)
    accuracy = models.JSONField("정확도", null=True, blank=True)

    class Meta:
        verbose_name = "분석 실행"
        verbose_name_plural = "분석 실행"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "status"])]

    def __str__(self) -> str:
        return f"run#{self.pk} {self.project_id} {self.status}"

    @property
    def is_active(self) -> bool:
        return self.status in {RunStatus.QUEUED, RunStatus.RUNNING}

    @property
    def elapsed_ms(self) -> int | None:
        if not self.started_at:
            return None
        end = self.finished_at or self.updated_at
        return int((end - self.started_at).total_seconds() * 1000)

    @property
    def token_usage(self) -> dict:
        calls = self.llm_calls or []
        return {
            "prompt": sum(c.get("prompt_tokens", 0) for c in calls),
            "completion": sum(c.get("completion_tokens", 0) for c in calls),
        }


class Assessment(TimeStampedModel):
    """The verdict for one requirement in one run (FR-13).

    INVARIANT (principle 3): ``verdict == MEET`` requires at least one Evidence
    row. Enforcement lives in two places, added in Phase 6 -- the serializer
    rejects the write with ``meet_without_evidence``, and the assessor coerces
    the verdict to CHECK rather than raising. ``has_evidence`` below is what
    both consult.

    ``ai_verdict`` is frozen at creation. Accuracy is measured from it, because
    measuring the human-edited ``verdict`` would always score 100%.
    """

    run = models.ForeignKey(
        AnalysisRun, on_delete=models.CASCADE, related_name="assessments"
    )
    requirement = models.ForeignKey(
        Requirement, on_delete=models.CASCADE, related_name="assessments"
    )

    verdict = models.CharField("판정", max_length=10, choices=Verdict.choices)
    ai_verdict = models.CharField("AI 판정", max_length=10, choices=Verdict.choices)
    evidence_state = models.CharField(
        "근거 상태",
        max_length=20,
        choices=EvidenceState.choices,
        default=EvidenceState.NOT_FOUND,
    )

    our_value = models.CharField("자사값", max_length=300, blank=True)
    ai_our_value = models.CharField("AI 자사값", max_length=300, blank=True)
    rationale = models.TextField("판정 사유", blank=True)
    gap_detail = models.TextField("미달 내용", blank=True)
    remedy = models.TextField("대체방안", blank=True)
    # Feeds the cross-clause pass. Example:
    # [{"field":"weight","op":"add","value":1.4,"unit":"kg","source":"카탈로그 2.3"}]
    remedy_side_effects = models.JSONField("대체방안 부작용", default=list)

    confidence = models.FloatField("확신도", null=True, blank=True)
    retrieval_query = models.TextField("검색 쿼리", blank=True)
    retrieved_chunk_ids = models.JSONField("검색된 청크", default=list)

    is_edited = models.BooleanField("사용자 수정", default=False)
    edited_at = models.DateTimeField("수정 시각", null=True, blank=True)

    class Meta:
        verbose_name = "판정"
        verbose_name_plural = "판정"
        ordering = ["requirement__order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "requirement"], name="uniq_assessment_per_run"
            )
        ]
        indexes = [models.Index(fields=["run", "verdict"])]

    def __str__(self) -> str:
        return f"{self.requirement_id} {self.verdict}"

    @property
    def has_evidence(self) -> bool:
        return self.pk is not None and self.evidences.exists()


class Evidence(TimeStampedModel):
    """A knowledge chunk supporting one verdict (FR-14).

    The document title, location, quote and parent text are snapshotted rather
    than read through ``chunk``. Re-indexing a knowledge document changes chunk
    ids, and a past run whose evidence display breaks cannot be trusted as an
    accuracy record. ``chunk`` is therefore SET_NULL and only used for
    debugging.
    """

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="evidences"
    )
    chunk = models.ForeignKey(
        KnowledgeChunk,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evidences",
    )

    doc_title = models.CharField("근거 문서", max_length=300)
    doc_no = models.CharField("문서번호", max_length=100, blank=True)
    location = models.CharField("위치", max_length=300, blank=True)
    page_no = models.IntegerField("페이지", null=True, blank=True)
    quote = models.TextField("인용", blank=True)
    parent_content = models.TextField("부모 청크 전문", blank=True)

    score = models.FloatField("결합 점수", default=0.0)
    semantic_score = models.FloatField("의미 점수", null=True, blank=True)
    keyword_score = models.FloatField("키워드 점수", null=True, blank=True)
    rank = models.IntegerField("순위", default=1)  # 1-based

    class Meta:
        verbose_name = "근거"
        verbose_name_plural = "근거"
        ordering = ["rank", "id"]

    def __str__(self) -> str:
        return f"#{self.rank} {self.doc_title} {self.location}"


class CrossClauseIssue(TimeStampedModel):
    """Two or more clauses that cannot be satisfied at once (FR-16).

    This cannot emerge from per-item judgement -- clause 3.1 does not know about
    3.2 -- so it is produced by an explicit separate pass
    (specs/06-analysis-pipeline.md section 5).
    """

    run = models.ForeignKey(
        AnalysisRun, on_delete=models.CASCADE, related_name="cross_issues"
    )
    clause_nos = models.JSONField("관련 조항", default=list)
    requirements = models.ManyToManyField(
        Requirement, blank=True, related_name="cross_issues"
    )
    kind = models.CharField(
        "종류", max_length=40, choices=IssueKind.choices, default=IssueKind.OTHER
    )
    title = models.CharField("제목", max_length=300)
    description = models.TextField("설명")  # includes the arithmetic
    severity = models.CharField(
        "심각도", max_length=20, choices=Severity.choices, default=Severity.MEDIUM
    )
    is_dismissed = models.BooleanField("무시", default=False)

    class Meta:
        verbose_name = "교차조항 이슈"
        verbose_name_plural = "교차조항 이슈"
        ordering = ["severity", "id"]

    def __str__(self) -> str:
        return f"{'/'.join(self.clause_nos)} {self.title}"


class InquiryDraft(TimeStampedModel):
    """One item of the technical-inquiry draft (FR-20)."""

    run = models.ForeignKey(
        AnalysisRun, on_delete=models.CASCADE, related_name="inquiries"
    )
    seq = models.IntegerField("순번")
    clause_refs = models.JSONField("관련 조항", default=list)
    source_kind = models.CharField(
        "후보 출처", max_length=20, choices=InquirySource.choices
    )
    body = models.TextField("문안")
    ai_body = models.TextField("AI 원본 문안", blank=True)
    is_included = models.BooleanField("포함", default=True)
    is_edited = models.BooleanField("사용자 수정", default=False)

    class Meta:
        verbose_name = "기술질의 초안"
        verbose_name_plural = "기술질의 초안"
        ordering = ["seq", "id"]

    def __str__(self) -> str:
        return f"[질의 {self.seq}] {'/'.join(self.clause_refs)}"


class ExportFile(TimeStampedModel):
    """A generated deliverable file (FR-21)."""

    run = models.ForeignKey(
        AnalysisRun, on_delete=models.CASCADE, related_name="exports"
    )
    kind = models.CharField("종류", max_length=20, choices=ExportKind.choices)
    file = models.FileField("파일", upload_to="exports/%Y/%m/")
    filename = models.CharField("파일명", max_length=300)

    class Meta:
        verbose_name = "산출물 파일"
        verbose_name_plural = "산출물 파일"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.filename
