"""Phase 1 acceptance: PDF extraction must match specs/08-sample-data.md exactly.

These tests are the guard against the failure mode described in
specs/05-rag-pipeline.md section 2.1 -- a one-row column shift that silently
turns every downstream verdict wrong. They assert whole rows, not substrings,
because a shifted value is still "present" in the page.

No DB, no Django ORM, no API key.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from documents.services.pdf_extract import ExtractionFailed, extract_pdf

ANNOUNCEMENT = settings.SAMPLES_DIR / "01_입찰공고문.pdf"
TECHSPEC = settings.SAMPLES_DIR / "02_기술사양서.pdf"


@pytest.fixture(scope="module")
def techspec():
    return extract_pdf(TECHSPEC)


@pytest.fixture(scope="module")
def announcement():
    return extract_pdf(ANNOUNCEMENT)


# ---------------------------------------------------------------------------
# Sample files present
# ---------------------------------------------------------------------------


def test_sample_files_exist():
    assert ANNOUNCEMENT.exists(), f"샘플 공고문이 없습니다: {ANNOUNCEMENT}"
    assert TECHSPEC.exists(), f"샘플 사양서가 없습니다: {TECHSPEC}"


# ---------------------------------------------------------------------------
# 기술사양서 — specs/08-sample-data.md section 2
# ---------------------------------------------------------------------------


def test_techspec_shape(techspec):
    assert techspec.page_count == 1
    assert techspec.table_count == 4, "제2~5장 조항 표 4개가 나와야 한다"
    assert techspec.doc_no == "KPG-2025-TS-0417"


def test_techspec_chapter2_performance(techspec):
    """The row that proves the column shift is gone.

    With ``pdftotext -layout`` this table comes out as
    ``2.2 총 광속 = 150 W 이하``. Asserting full rows catches that.
    """
    table = techspec.all_tables()[0]
    assert table.header == ["조항", "항목", "요구조건"]
    assert table.body == [
        ["2.1", "소비전력", "150 W 이하"],
        ["2.2", "총 광속 (밝기)", "20,000 lm 이상"],
        ["2.3", "광효율", "140 lm/W 이상"],
        ["2.4", "색온도", "5,700 K"],
        ["2.5", "수명", "50,000 시간 이상"],
    ]


def test_techspec_chapter3_structure(techspec):
    table = techspec.all_tables()[1]
    assert table.header == ["조항", "항목", "요구조건"]
    assert table.body == [
        ["3.1", "방수·방진 등급", "IP66 이상"],
        ["3.2", "본체 무게", "8 kg 이하"],
        ["3.3", "동작 온도범위", "-20℃ ~ 50℃"],
        ["3.4", "본체 재질", "알루미늄 다이캐스팅"],
    ]


def test_techspec_chapter4_tests(techspec):
    """4.4 keeps its 기준 value.

    specs/08-sample-data.md section 2.4 flags this table as visually ambiguous in
    the original layout. pdfplumber resolves it cleanly, so 4.4 is NOT empty and
    no blank-cell warning is expected.
    """
    table = techspec.all_tables()[2]
    assert table.header == ["조항", "시험항목", "기준"]
    assert table.body == [
        ["4.1", "광속 및 광효율 측정", "조항 2.2, 2.3 기준"],
        ["4.2", "방수·방진 시험", "IP66"],
        ["4.3", "내염수분무 시험", "염해 환경 대응, 240시간"],
        ["4.4", "내진동 시험", "KS C 7658"],
    ]


def test_techspec_chapter5_quality(techspec):
    table = techspec.all_tables()[3]
    assert table.header == ["조항", "항목", "요구조건"]
    assert table.body == [
        ["5.1", "KS 인증", "보유"],
        ["5.2", "고효율에너지기자재 인증", "보유"],
        ["5.3", "보증기간", "납품 후 3년 이상"],
        ["5.4", "납품실적", "최근 5년 발전소 납품실적 3건 이상"],
    ]


def test_techspec_all_17_clauses_present(techspec):
    """The 17 clauses FR-03 must find. Extraction cannot lose any of them."""
    found = {
        row[0]
        for table in techspec.all_tables()
        for row in table.body
        if row and row[0][:1].isdigit()
    }
    expected = {
        "2.1", "2.2", "2.3", "2.4", "2.5",
        "3.1", "3.2", "3.3", "3.4",
        "4.1", "4.2", "4.3", "4.4",
        "5.1", "5.2", "5.3", "5.4",
    }
    assert found == expected
    assert len(expected) == 17


def test_techspec_narrative_context_preserved(techspec):
    """Text outside tables survives -- it is judgement context, not decoration.

    "해안에서 약 2km" is why IP66 and the salt-spray test are demanded, and it
    becomes ``Requirement.context_text`` for clauses 3.1 and 4.3.
    """
    text = techspec.full_text
    assert "해안에서 약 2km" in text
    assert "IP66 이상으로 요구한다" in text
    assert "미달 시 대체방안을 대응표에 명시" in text
    assert "공인시험기관 성적서를 제출" in text


def test_techspec_no_warnings(techspec):
    """A clean read produces zero warnings.

    If a future pdfplumber version starts mis-detecting these tables, blank
    cells or a clause-number gap will appear here first.
    """
    assert techspec.warnings == []


# ---------------------------------------------------------------------------
# 입찰공고문 — specs/08-sample-data.md section 1
# ---------------------------------------------------------------------------


def test_announcement_shape(announcement):
    assert announcement.page_count == 2
    assert announcement.table_count == 3, "개요 / 일정 / 제출서류 표 3개"
    assert announcement.doc_no == "KPG-2025-EQ-0417"


def test_announcement_overview(announcement):
    table = announcement.all_tables()[0]
    assert table.header == ["구분", "내용"]
    assert table.body == [
        ["사업명", "○○화력발전소 구내 LED 투광등 교체"],
        ["공고기관", "한국발전기술공사 자재구매처"],
        ["구매품목", "LED 투광등 150W급"],
        ["수량", "200대"],
        ["추정가격", "금 240,000,000원 (부가세 별도)"],
        ["납품장소", "○○화력발전소 자재창고 (충청남도 소재)"],
        ["납품기한", "계약체결일로부터 60일 이내"],
    ]


def test_announcement_item_name_drives_model_hint(announcement):
    """``LED 투광등 150W급`` is the basis for model matching (TRAP-1).

    Without this value the retriever cannot filter LT-200 chunks out of
    LT-150 requirements.
    """
    overview = dict(
        (row[0], row[1]) for row in announcement.all_tables()[0].body if len(row) >= 2
    )
    assert overview["구매품목"] == "LED 투광등 150W급"
    assert "150" in overview["구매품목"]
    # 납품기한 60일 is the constraint the lead-time cross-check compares against.
    assert overview["납품기한"] == "계약체결일로부터 60일 이내"


def test_announcement_schedule(announcement):
    table = announcement.all_tables()[1]
    assert table.header == ["구분", "일시", "비고"]
    assert table.body == [
        ["공고일", "2025-07-01", ""],
        ["기술질의 접수마감", "2025-07-10", "전자우편"],
        ["입찰서 제출마감", "2025-07-24 10:00", "전자입찰시스템"],
        ["개찰", "2025-07-24 11:00", ""],
    ]


def test_announcement_submission_documents(announcement):
    """All 8 submission documents with 연번 / 서류명 / 비고 (FR-04)."""
    table = announcement.all_tables()[2]
    assert table.header == ["연번", "서류명", "비고"]
    assert table.body == [
        ["1", "입찰참가신청서", "소정양식"],
        ["2", "사업자등록증 사본", ""],
        ["3", "KS 인증서 사본", ""],
        ["4", "고효율에너지기자재 인증서 사본", ""],
        ["5", "납품실적증명서", "발주처 직인 날인본"],
        ["6", "기술규격 대응표", "항목별 근거 명시"],
        ["7", "제품 카탈로그", ""],
        ["8", "공인시험기관 시험성적서", "기술사양서 제4장 전체"],
    ]
    assert len(table.body) == 8


def test_announcement_participation_and_notes(announcement):
    """참가자격 3건과 기타사항은 표가 아니라 본문이다."""
    text = announcement.full_text
    assert "LED 조명 제조업 등록을 필한 자" in text
    assert "KS 인증을 보유한 자" in text
    assert "최근 5년 이내 발전소 납품실적이 3건 이상인 자" in text
    # 5.2 is why the compliance matrix needs 사유/대체방안 columns (FR-18).
    assert "사유와 대체방안을 대응표에 기재" in text


def test_announcement_no_warnings(announcement):
    """Blank 비고 cells are legitimate and must not generate noise.

    Warnings are scoped to clause tables, where a blank cell really does mean a
    lost requirement value.
    """
    assert announcement.warnings == []


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_scanned_pdf_rejected(tmp_path):
    """A PDF with no text layer fails loudly. OCR is out of scope."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    blank = tmp_path / "blank.pdf"
    with blank.open("wb") as fh:
        writer.write(fh)

    with pytest.raises(ExtractionFailed) as exc:
        extract_pdf(blank)
    assert "스캔" in str(exc.value)


# ---------------------------------------------------------------------------
# Markdown serialization for prompts
# ---------------------------------------------------------------------------


def test_tables_serialize_to_markdown(techspec):
    """Prompts receive Markdown tables (specs/06-analysis-pipeline.md 2.1)."""
    from common.tables import pages_to_markdown

    md = pages_to_markdown(techspec.pages)
    assert "| 조항 | 항목 | 요구조건 |" in md
    assert "| 2.1 | 소비전력 | 150 W 이하 |" in md
    assert "| 3.1 | 방수·방진 등급 | IP66 이상 |" in md
    # Every clause table must be rendered.
    assert md.count("|---|---|---|") == 4
