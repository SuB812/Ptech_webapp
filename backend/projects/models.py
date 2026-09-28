"""Bid project models (specs/03-data-model.md section 2)."""

from django.db import models

from common.enums import SubmissionStatus
from common.models import TimeStampedModel


class BidProject(TimeStampedModel):
    """One announcement being analysed: documents, requirements, runs.

    ``quantity`` and ``estimated_price`` are text on purpose. The announcement
    wording is reproduced verbatim in the deliverables, and no arithmetic is
    done on them (costing is out of scope, specs/00-overview.md section 3).
    """

    title = models.CharField("사업명", max_length=300)
    bid_no = models.CharField("공고번호", max_length=100, blank=True, db_index=True)
    org = models.CharField("공고기관", max_length=200, blank=True)
    item_name = models.CharField("구매품목", max_length=200, blank=True)
    quantity = models.CharField("수량", max_length=50, blank=True)
    estimated_price = models.CharField("추정가격", max_length=100, blank=True)
    delivery_place = models.CharField("납품장소", max_length=300, blank=True)
    delivery_term = models.CharField("납품기한", max_length=200, blank=True)

    announced_on = models.DateField("공고일", null=True, blank=True)
    inquiry_due_at = models.DateTimeField("기술질의 접수마감", null=True, blank=True)
    bid_due_at = models.DateTimeField("입찰서 제출마감", null=True, blank=True)
    opening_at = models.DateTimeField("개찰", null=True, blank=True)

    spec_doc_no = models.CharField("사양서 문서번호", max_length=100, blank=True)
    notes = models.TextField("기타 사항", blank=True)

    class Meta:
        verbose_name = "입찰 건"
        verbose_name_plural = "입찰 건"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.bid_no or '(공고번호 없음)'} {self.title}"


class ParticipationRequirement(TimeStampedModel):
    """Eligibility clause from the announcement (샘플: 공고 3.1~3.3).

    Kept separate from ``Requirement`` because these come from the announcement,
    not the spec sheet, and appear in the checklist rather than the matrix.
    Clause 3.3 duplicates spec clause 5.4 in substance; both are kept because
    the deliverables must cite both sources (specs/08-sample-data.md 1.3).
    """

    project = models.ForeignKey(
        BidProject, on_delete=models.CASCADE, related_name="participation_reqs"
    )
    seq = models.CharField("연번", max_length=20)
    text = models.TextField("자격 요건")
    status = models.CharField(
        "자사 상태", max_length=20, choices=SubmissionStatus.choices,
        default=SubmissionStatus.UNCERTAIN,
    )
    note = models.TextField("비고", blank=True)

    class Meta:
        verbose_name = "입찰 참가자격"
        verbose_name_plural = "입찰 참가자격"
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "seq"], name="uniq_participation_per_project"
            )
        ]

    def __str__(self) -> str:
        return f"{self.seq} {self.text[:40]}"


class SubmissionItem(TimeStampedModel):
    """Required submission document (FR-04). 샘플 기준 8건."""

    project = models.ForeignKey(
        BidProject, on_delete=models.CASCADE, related_name="submission_items"
    )
    seq = models.IntegerField("연번")
    name = models.CharField("서류명", max_length=200)
    note = models.CharField("공고 비고", max_length=300, blank=True)
    status = models.CharField(
        "자사 상태", max_length=20, choices=SubmissionStatus.choices,
        default=SubmissionStatus.UNCERTAIN,
    )
    evidence_text = models.TextField("매핑 근거", blank=True)
    is_checked = models.BooleanField("확인", default=False)

    class Meta:
        verbose_name = "제출서류"
        verbose_name_plural = "제출서류"
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "seq"], name="uniq_submission_seq_per_project"
            )
        ]

    def __str__(self) -> str:
        return f"{self.seq}. {self.name}"
