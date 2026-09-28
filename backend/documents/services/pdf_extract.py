"""PDF text and table extraction for input documents (FR-02).

**Tables must come from ``pdfplumber.extract_tables()``.** Layout-based text
extraction is unusable on the sample spec: ``pdftotext -layout`` shifts the
requirement column up by one row, producing ``2.2 총 광속 = 150 W 이하``, and
every verdict downstream is then wrong (specs/05-rag-pipeline.md section 2.1).

The extractor reports problems as warnings and never repairs them. A shifted or
missing cell is a human decision on the FR-07 review screen.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from common.tables import normalize_rows

logger = logging.getLogger(__name__)

# Minimum extractable characters before we call the file a scan. OCR is out of
# scope (specs/00-overview.md section 3), so we fail loudly instead.
MIN_TEXT_CHARS = 50

CLAUSE_RE = re.compile(r"^\d+\.\d+$")
DOC_NO_RE = re.compile(
    r"(?:문서\s*번호|공고\s*번호)\s*[:：]?\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)"
)


class ExtractionFailed(Exception):
    """No usable text layer. Maps to HTTP 422 `extraction_failed`."""


@dataclass
class ExtractedTable:
    index: int
    rows: list[list[str]]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> list[list[str]]:
        return self.rows[1:] if len(self.rows) > 1 else []


@dataclass
class ExtractedPage:
    page_no: int  # 1-based
    text: str
    tables: list[ExtractedTable] = field(default_factory=list)


@dataclass
class ExtractionResult:
    page_count: int
    pages: list[ExtractedPage]
    doc_no: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def table_count(self) -> int:
        return sum(len(p.tables) for p in self.pages)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def table(self, page_no: int, index: int) -> ExtractedTable | None:
        for page in self.pages:
            if page.page_no == page_no:
                for t in page.tables:
                    if t.index == index:
                        return t
        return None

    def all_tables(self) -> list[ExtractedTable]:
        return [t for p in self.pages for t in p.tables]


def _text_outside_tables(page: pdfplumber.page.Page) -> str:
    """Page text with table regions removed.

    Narrative sentences outside tables carry judgement context -- "해안에서 약
    2km", "미달 시 대체방안을 대응표에 명시" -- so they must survive separately
    from the table cells (FR-02).
    """
    try:
        boxes = [t.bbox for t in page.find_tables()]
    except Exception as exc:  # noqa: BLE001 - detection is best-effort
        logger.warning("find_tables failed on page %s: %s", page.page_number, exc)
        boxes = []

    if not boxes:
        return (page.extract_text() or "").strip()

    def outside(obj: dict) -> bool:
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

    try:
        return (page.filter(outside).extract_text() or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("filtered extract_text failed on page %s: %s", page.page_number, exc)
        return (page.extract_text() or "").strip()


def _is_clause_table(table: ExtractedTable) -> bool:
    """True when the first column holds clause numbers like ``2.1``."""
    return any(CLAUSE_RE.match(row[0]) for row in table.body if row and row[0])


def _check_table(table: ExtractedTable, page_no: int, warnings: list[str]) -> None:
    """Validation per specs/05-rag-pipeline.md section 2.3."""
    if not table.rows:
        warnings.append(f"p.{page_no} 표 {table.index + 1}: 행이 없습니다.")
        return

    width = len(table.header)
    for row_i, row in enumerate(table.body, start=1):
        if len(row) != width:
            warnings.append(
                f"p.{page_no} 표 {table.index + 1} {row_i}행: 열 수가 헤더와 다릅니다 "
                f"({len(row)} vs {width}). 표 인식이 틀렸을 수 있습니다."
            )

    if not _is_clause_table(table):
        # Optional columns (비고 etc.) are legitimately blank in non-clause
        # tables, so blank-cell warnings there would be pure noise.
        return

    # Blank cells inside a clause table mean a requirement value is missing or
    # has drifted into a neighbouring row. A human must look.
    for row in table.body:
        if not row or not row[0]:
            continue
        for col_i, cell in enumerate(row):
            if not cell.strip():
                col_name = table.header[col_i] if col_i < width else f"{col_i + 1}열"
                warnings.append(
                    f"조항 {row[0]} 의 '{col_name}' 칸이 비어 있습니다. "
                    f"원본을 확인하세요 (자동 보정하지 않습니다)."
                )

    # Clause numbers should run consecutively inside one table.
    nums = [row[0] for row in table.body if row and CLAUSE_RE.match(row[0])]
    parsed = [tuple(int(x) for x in n.split(".")) for n in nums]
    for prev, cur in zip(parsed, parsed[1:]):
        if cur[0] == prev[0] and cur[1] != prev[1] + 1:
            warnings.append(
                f"조항 번호가 연속되지 않습니다: {prev[0]}.{prev[1]} 다음에 "
                f"{cur[0]}.{cur[1]} 이 옵니다. 누락 여부를 확인하세요."
            )


def extract_pdf(path: str | Path) -> ExtractionResult:
    """Extract every page of a PDF.

    Raises ``ExtractionFailed`` when there is no usable text layer.
    """
    path = Path(path)
    pages: list[ExtractedPage] = []
    warnings: list[str] = []

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            raw_tables = page.extract_tables() or []
            tables = [
                ExtractedTable(index=i, rows=normalize_rows(rows))
                for i, rows in enumerate(raw_tables)
            ]
            extracted = ExtractedPage(
                page_no=page.page_number,
                text=_text_outside_tables(page),
                tables=tables,
            )
            for table in tables:
                _check_table(table, extracted.page_no, warnings)
            pages.append(extracted)

    result = ExtractionResult(page_count=page_count, pages=pages, warnings=warnings)

    if page_count == 0:
        raise ExtractionFailed("페이지를 읽을 수 없습니다.")

    # Table cells count as extracted content: a spec sheet can be almost
    # entirely tabular and still be perfectly readable.
    body_chars = len(result.full_text.replace(" ", ""))
    cell_chars = sum(
        len(cell.replace(" ", "")) for t in result.all_tables() for row in t.rows for cell in row
    )
    if body_chars + cell_chars < MIN_TEXT_CHARS:
        raise ExtractionFailed(
            "텍스트를 추출할 수 없습니다. 스캔된 PDF 로 보입니다. "
            "OCR 은 이번 범위에 없으므로 텍스트 레이어가 있는 PDF 를 올려주세요."
        )

    result.doc_no = _find_doc_no(result)
    return result


def _find_doc_no(result: ExtractionResult) -> str:
    """First 문서번호/공고번호 in the document.

    Requiring the label keeps it from matching a cross-reference such as
    ``기술사양서(KPG-2025-TS-0417)`` in the announcement.
    """
    for page in result.pages:
        match = DOC_NO_RE.search(page.text)
        if match:
            return match.group(1)
    for table in result.all_tables():
        for row in table.rows:
            match = DOC_NO_RE.search(" ".join(row))
            if match:
                return match.group(1)
    return ""
