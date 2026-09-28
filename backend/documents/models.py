"""Input document and requirement models (specs/03-data-model.md section 3)."""

from django.db import models

from common.enums import Category, DocStatus, DocType
from common.models import TimeStampedModel
from projects.models import BidProject


class SourceDocument(TimeStampedModel):
    """An uploaded announcement or spec sheet (FR-01).

    INVARIANT: a SourceDocument is never vector-indexed. There is deliberately
    no relation from here to ``knowledge.KnowledgeChunk``, so indexing an input
    document is structurally impossible rather than merely discouraged
    (principle 1, specs/00-overview.md section 5).
    """

    project = models.ForeignKey(
        BidProject, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField("문서 종류", max_length=20, choices=DocType.choices)
    file = models.FileField("파일", upload_to="bids/%Y/%m/")
    original_name = models.CharField("원본 파일명", max_length=300)
    doc_no = models.CharField("문서번호", max_length=100, blank=True)
    page_count = models.IntegerField("페이지 수", default=0)
    status = models.CharField(
        "상태", max_length=20, choices=DocStatus.choices, default=DocStatus.UPLOADED
    )
    error_message = models.TextField("오류 사유", blank=True)

    class Meta:
        verbose_name = "입력 문서"
        verbose_name_plural = "입력 문서"
        ordering = ["doc_type", "id"]

    def __str__(self) -> str:
        return f"[{self.get_doc_type_display()}] {self.original_name}"

    @property
    def table_count(self) -> int:
        return sum(len(page.tables) for page in self.pages.all())


class DocumentPage(TimeStampedModel):
    """Per-page extraction output (FR-02).

    ``tables`` keeps the raw 2-D arrays for two reasons: a human must be able to
    compare them against the original when extraction looks wrong, and a prompt
    change can be re-run without re-parsing the PDF.
    """

    document = models.ForeignKey(
        SourceDocument, on_delete=models.CASCADE, related_name="pages"
    )
    page_no = models.IntegerField("페이지 번호")  # 1-based
    text = models.TextField("표 밖 본문", blank=True)
    tables = models.JSONField("표", default=list)

    class Meta:
        verbose_name = "문서 페이지"
        verbose_name_plural = "문서 페이지"
        ordering = ["page_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "page_no"], name="uniq_page_per_document"
            )
        ]

    def __str__(self) -> str:
        return f"{self.document_id} p.{self.page_no}"


class Requirement(TimeStampedModel):
    """One extracted requirement clause (FR-03).

    ``requirement_text`` may be blank: when a table cell is empty the extractor
    must leave it empty and warn rather than guess a value
    (specs/06-analysis-pipeline.md 2.2, rule 5).

    The ``ai_*`` columns preserve what the model produced before any human edit.
    Accuracy is always measured against the AI values, never the edited ones.
    """

    project = models.ForeignKey(
        BidProject, on_delete=models.CASCADE, related_name="requirements"
    )
    source_document = models.ForeignKey(
        SourceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requirements",
    )

    clause_no = models.CharField("조항", max_length=30)
    chapter = models.CharField("구분", max_length=100, blank=True)
    category = models.CharField(
        "분류", max_length=20, choices=Category.choices, default=Category.OTHER
    )
    item = models.CharField("항목", max_length=200)
    requirement_text = models.TextField("요구조건", blank=True)
    context_text = models.TextField("관련 서술", blank=True)
    source_page = models.IntegerField("출처 페이지", null=True, blank=True)
    order = models.IntegerField("표시 순서", default=0)

    is_active = models.BooleanField("분석 대상", default=True)
    is_graded = models.BooleanField("채점 대상", default=False)
    is_edited = models.BooleanField("사용자 수정", default=False)

    ai_item = models.CharField(max_length=200, blank=True)
    ai_requirement_text = models.TextField(blank=True)
    ai_category = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "요구사항"
        verbose_name_plural = "요구사항"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "clause_no", "item"],
                name="uniq_requirement_per_project",
            )
        ]
        indexes = [
            models.Index(fields=["project", "is_active"]),
            models.Index(fields=["project", "is_graded"]),
        ]

    def __str__(self) -> str:
        return f"{self.clause_no} {self.item}"

    def snapshot_ai_values(self) -> None:
        """Copy the current values into the ``ai_*`` columns.

        Called once by the extractor, before any human can touch the row.
        """
        self.ai_item = self.item
        self.ai_requirement_text = self.requirement_text
        self.ai_category = self.category
