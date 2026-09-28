"""Requirement extraction (FR-03, FR-04, FR-05; specs/06-analysis-pipeline.md section 2).

LLM output is never trusted as-is: the category is clamped to the allowed set,
duplicates are dropped, dates are parsed strictly, and the clause order is
recomputed numerically. Anything the model could not read becomes a warning for
the human review screen (FR-07) rather than a guess.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from common.enums import Category, DocType
from common.llm import CallLog, chat_json, load_prompt
from common.sorting import clause_sort_key
from common.tables import pages_to_markdown
from documents.models import DocumentPage, Requirement, SourceDocument
from projects.models import BidProject, ParticipationRequirement, SubmissionItem

logger = logging.getLogger(__name__)

PROMPT_NAME = "extract_requirements"

DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
_DATE_FIELDS = ("announced_on",)
_DATETIME_FIELDS = ("inquiry_due_at", "bid_due_at", "opening_at")
_TEXT_FIELDS = (
    "title", "bid_no", "org", "item_name", "quantity",
    "estimated_price", "delivery_place", "delivery_term", "spec_doc_no",
)


@dataclass
class ExtractionSummary:
    requirement_count: int = 0
    submission_count: int = 0
    participation_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _clamp_category(value: str) -> str:
    return value if value in Category.values else Category.OTHER


def _rendered_prompt(document: SourceDocument) -> str:
    pages = list(document.pages.all())
    body = "\n\n".join(f"[p.{p.page_no}]\n{p.text}" for p in pages if p.text.strip())

    class _Page:
        def __init__(self, page: DocumentPage):
            self.page_no = page.page_no
            self.tables = [
                type("T", (), {"index": t.get("index", i), "rows": t.get("rows", [])})()
                for i, t in enumerate(page.tables or [])
            ]

    tables_md = pages_to_markdown([_Page(p) for p in pages])

    return load_prompt(PROMPT_NAME).format(
        allowed_categories=", ".join(Category.values),
        doc_type_label=document.get_doc_type_display(),
        doc_no=document.doc_no or "(없음)",
        body_text=body or "(표 밖 본문 없음)",
        tables_markdown=tables_md or "(표 없음)",
    )


def extract_from_document(
    document: SourceDocument, *, log: CallLog | None = None
) -> dict:
    """One LLM call for one input document."""
    return chat_json(
        PROMPT_NAME, rendered_prompt=_rendered_prompt(document), log=log
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _apply_bid_info(project: BidProject, info: dict, warnings: list[str]) -> None:
    """FR-05. Only fills blanks; a value a human typed is never overwritten."""
    changed: list[str] = []

    for field_name in _TEXT_FIELDS:
        value = (info.get(field_name) or "").strip()
        if not value:
            continue
        if field_name == "title" and project.title:
            continue
        if getattr(project, field_name):
            continue
        setattr(project, field_name, value[: project._meta.get_field(field_name).max_length])
        changed.append(field_name)

    for field_name in _DATE_FIELDS + _DATETIME_FIELDS:
        raw = (info.get(field_name) or "").strip()
        if not raw or getattr(project, field_name):
            continue
        parsed = _parse_date(raw)
        if parsed is None:
            warnings.append(f"{field_name} 날짜를 해석할 수 없습니다: {raw!r}")
            continue
        if field_name in _DATE_FIELDS:
            setattr(project, field_name, parsed.date())
        else:
            setattr(project, field_name, timezone.make_aware(parsed))
        changed.append(field_name)

    if changed:
        project.save(update_fields=changed + ["updated_at"])


def _save_requirements(
    project: BidProject,
    document: SourceDocument,
    rows: list[dict],
    warnings: list[str],
) -> int:
    seen: set[tuple[str, str]] = set(
        project.requirements.values_list("clause_no", "item")
    )
    created: list[Requirement] = []

    for row in rows:
        clause_no = str(row.get("clause_no") or "").strip()[:30]
        item = str(row.get("item") or "").strip()[:200]
        if not clause_no or not item:
            warnings.append(f"조항번호 또는 항목이 비어 추출을 건너뜀: {row!r}")
            continue
        if (clause_no, item) in seen:
            warnings.append(f"중복 조항을 건너뜀: {clause_no} {item}")
            continue
        seen.add((clause_no, item))

        requirement = Requirement(
            project=project,
            source_document=document,
            clause_no=clause_no,
            chapter=str(row.get("chapter") or "").strip()[:100],
            category=_clamp_category(str(row.get("category") or "")),
            item=item,
            requirement_text=str(row.get("requirement_text") or "").strip(),
            context_text=str(row.get("context_text") or "").strip(),
            source_page=row.get("source_page") if isinstance(row.get("source_page"), int) else None,
        )
        # Freeze the AI values before any human can edit them: accuracy is always
        # measured from these.
        requirement.snapshot_ai_values()
        if not requirement.requirement_text:
            warnings.append(
                f"조항 {clause_no} ({item}) 의 요구조건이 비어 있습니다. "
                f"원본을 확인하세요."
            )
        created.append(requirement)

    Requirement.objects.bulk_create(created)
    return len(created)


def _save_submissions(project: BidProject, rows: list[dict], warnings: list[str]) -> int:
    existing = set(project.submission_items.values_list("seq", flat=True))
    made = 0
    for row in rows:
        seq = row.get("seq")
        if not isinstance(seq, int):
            warnings.append(f"제출서류 연번이 정수가 아닙니다: {row!r}")
            continue
        if seq in existing:
            continue
        name = str(row.get("name") or "").strip()[:200]
        if not name:
            continue
        SubmissionItem.objects.create(
            project=project, seq=seq, name=name,
            note=str(row.get("note") or "").strip()[:300],
        )
        existing.add(seq)
        made += 1
    return made


def _save_participation(project: BidProject, rows: list[dict], warnings: list[str]) -> int:
    existing = set(project.participation_reqs.values_list("seq", flat=True))
    made = 0
    for row in rows:
        seq = str(row.get("seq") or "").strip()[:20]
        text = str(row.get("text") or "").strip()
        if not seq or not text:
            continue
        if seq in existing:
            continue
        ParticipationRequirement.objects.create(project=project, seq=seq, text=text)
        existing.add(seq)
        made += 1
    return made


def _renumber(project: BidProject) -> None:
    """Order by clause number numerically, so 2.10 follows 2.2."""
    requirements = list(project.requirements.all())
    requirements.sort(key=lambda r: clause_sort_key(r.clause_no))
    for index, requirement in enumerate(requirements, start=1):
        requirement.order = index
    Requirement.objects.bulk_update(requirements, ["order"])


def extract_project(
    project: BidProject, *, replace: bool = False, log: CallLog | None = None
) -> ExtractionSummary:
    """Extract requirements, submissions, eligibility and header from every document.

    The announcement is processed first so its header information wins, and its
    eligibility clauses keep their ``공고 N`` prefix.
    """
    summary = ExtractionSummary()

    if replace:
        with transaction.atomic():
            project.requirements.all().delete()
            project.submission_items.all().delete()
            project.participation_reqs.all().delete()

    documents = sorted(
        project.documents.all(),
        key=lambda d: 0 if d.doc_type == DocType.ANNOUNCEMENT else 1,
    )
    if not documents:
        summary.warnings.append("업로드된 문서가 없습니다.")
        return summary

    for document in documents:
        if not document.pages.exists():
            summary.warnings.append(
                f"{document.original_name}: 추출된 페이지가 없어 건너뜁니다."
            )
            continue

        data = extract_from_document(document, log=log)

        for warning in data.get("warnings") or []:
            summary.warnings.append(f"{document.original_name}: {warning}")

        if document.doc_type == DocType.ANNOUNCEMENT:
            _apply_bid_info(project, data.get("bid_info") or {}, summary.warnings)
            summary.submission_count += _save_submissions(
                project, data.get("submission_items") or [], summary.warnings
            )
            summary.participation_count += _save_participation(
                project, data.get("participation_reqs") or [], summary.warnings
            )
        else:
            # A spec sheet can carry its own document number for the header.
            info = data.get("bid_info") or {}
            if info.get("spec_doc_no") and not project.spec_doc_no:
                project.spec_doc_no = str(info["spec_doc_no"])[:100]
                project.save(update_fields=["spec_doc_no", "updated_at"])

        summary.requirement_count += _save_requirements(
            project, document, data.get("requirements") or [], summary.warnings
        )

    _renumber(project)

    clause_count = project.requirements.count()
    if clause_count == 0:
        summary.warnings.append("요구사항을 추출하지 못했습니다.")

    logger.info(
        "extracted project %s: %s requirements, %s submissions, %s eligibility",
        project.pk, summary.requirement_count,
        summary.submission_count, summary.participation_count,
    )
    return summary
