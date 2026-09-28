"""Shared vocabulary for the whole project.

Transcribed from specs/03-data-model.md section 1. Internal values are English;
only the human-facing labels are Korean (CLAUDE.md section 7).
"""

from django.db import models


class DocType(models.TextChoices):
    """Input document kind. These are never vector-indexed (principle 1)."""

    ANNOUNCEMENT = "announcement", "입찰공고문"
    TECHSPEC = "techspec", "기술사양서"


class KnowledgeKind(models.TextChoices):
    """Our own reference material, which *is* vector-indexed."""

    CATALOG = "catalog", "제품카탈로그"
    QA = "qa", "인증·시험·실적"
    OTHER = "other", "기타"


class Category(models.TextChoices):
    """Requirement classification (FR-06).

    ``PRESSURE_DROP`` has no instance in the LED sample; it is kept for filter
    products (specs/01-functional-requirements.md FR-06).
    """

    DIMENSION = "dimension", "제품 치수"
    FILTER_GRADE = "filter_grade", "등급"
    EFFICIENCY = "efficiency", "효율"
    PRESSURE_DROP = "pressure_drop", "차압"
    TEST_STANDARD = "test_standard", "시험규격"
    CERTIFICATION = "certification", "인증"
    DELIVERY = "delivery", "납기"
    SUBMISSION = "submission", "제출서류"
    PERFORMANCE = "performance", "성능"
    MATERIAL = "material", "재질·구조"
    TRACK_RECORD = "track_record", "실적"
    OTHER = "other", "기타"


class Verdict(models.TextChoices):
    """The only three verdicts. MEET requires at least one Evidence row."""

    MEET = "MEET", "충족"
    GAP = "GAP", "보완 필요"
    CHECK = "CHECK", "확인 필요"


class EvidenceState(models.TextChoices):
    """Why a verdict came out the way it did.

    ``FOUND_ABSENT`` vs ``NOT_FOUND`` is the distinction TRAP-4 tests: our own
    material explicitly saying "미보유" is a finding, not a search failure
    (specs/09-acceptance-tests.md TRAP-4).
    """

    FOUND_SUFFICIENT = "found_sufficient", "근거 확인, 충족"
    FOUND_INSUFFICIENT = "found_insufficient", "근거 확인, 미달"
    FOUND_ABSENT = "found_absent", "자사 자료에 미보유 명시"
    NOT_FOUND = "not_found", "근거 검색 실패"


class RunStatus(models.TextChoices):
    QUEUED = "queued", "대기"
    RUNNING = "running", "진행중"
    DONE = "done", "완료"
    FAILED = "failed", "실패"


class DocStatus(models.TextChoices):
    UPLOADED = "uploaded", "업로드됨"
    PARSING = "parsing", "추출중"
    PARSED = "parsed", "추출완료"
    INDEXING = "indexing", "색인중"
    INDEXED = "indexed", "색인완료"
    FAILED = "failed", "실패"


class SubmissionStatus(models.TextChoices):
    HAVE = "have", "보유"
    NEED = "need", "발급 필요"
    UNCERTAIN = "uncertain", "확인 필요"


class ChunkType(models.TextChoices):
    """Shape of a knowledge chunk (specs/05-rag-pipeline.md section 3.2)."""

    TABLE = "table", "표 전체"
    TABLE_ROW = "table_row", "표 행"
    TEXT = "text", "본문"
    HEADING = "heading", "헤딩"


class IssueKind(models.TextChoices):
    """Cross-clause conflict kind (FR-16)."""

    OPTION_SIDE_EFFECT = "option_side_effect", "선택사양 부작용"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive", "동시 만족 불가"
    OTHER = "other", "기타"


class Severity(models.TextChoices):
    HIGH = "high", "높음"
    MEDIUM = "medium", "보통"
    LOW = "low", "낮음"


class InquirySource(models.TextChoices):
    """Where a technical-inquiry draft item came from (FR-20)."""

    CHECK = "check", "확인 필요 항목"
    GAP_REMEDY = "gap_remedy", "대체방안 승인 요청"
    CROSS_CLAUSE = "cross_clause", "교차조항 상충"


class ExportKind(models.TextChoices):
    XLSX = "xlsx", "Excel"
    MARKDOWN = "markdown", "Markdown 보고서"


# Labels for side-effect fields, used in the compliance matrix and inquiry text
# (specs/10-output-templates.md section 1.1).
SIDE_EFFECT_FIELD_LABELS = {
    "weight": "무게",
    "price": "단가",
    "lead_time": "납기",
    "temperature": "온도",
    "other": "기타",
}
