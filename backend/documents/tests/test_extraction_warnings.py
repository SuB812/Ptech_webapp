"""Proves the extraction warning logic is live.

``test_techspec_no_warnings`` asserts an empty warning list, which would pass
just as well if the warning code were dead. These synthetic tables exercise each
branch so the clean-sample assertion means something.
"""

from __future__ import annotations

from documents.services.pdf_extract import ExtractedTable, _check_table, _is_clause_table


def warnings_for(rows: list[list[str]]) -> list[str]:
    out: list[str] = []
    _check_table(ExtractedTable(index=0, rows=rows), page_no=1, warnings=out)
    return out


def test_blank_requirement_cell_warns():
    """The 4.4-style failure: a clause exists but its value drifted away.

    This is the case specs/08-sample-data.md 2.4 worried about. pdfplumber does
    not produce it on our sample, but the guard must fire if it ever does.
    """
    found = warnings_for(
        [
            ["조항", "시험항목", "기준"],
            ["4.3", "내염수분무 시험", "염해 환경 대응, 240시간"],
            ["4.4", "내진동 시험", ""],
        ]
    )
    assert len(found) == 1
    assert "조항 4.4" in found[0]
    assert "기준" in found[0]
    assert "자동 보정하지 않습니다" in found[0]


def test_clause_number_gap_warns():
    found = warnings_for(
        [
            ["조항", "항목", "요구조건"],
            ["2.1", "소비전력", "150 W 이하"],
            ["2.3", "광효율", "140 lm/W 이상"],
        ]
    )
    assert any("연속되지 않습니다" in w for w in found)


def test_column_count_mismatch_warns():
    found = warnings_for(
        [
            ["조항", "항목", "요구조건"],
            ["2.1", "소비전력"],
        ]
    )
    assert any("열 수가 헤더와 다릅니다" in w for w in found)


def test_blank_cell_in_non_clause_table_is_silent():
    """Blank 비고 cells are normal in the announcement tables.

    Warning on these would bury the real signal under noise, which is why the
    blank-cell check is scoped to clause tables.
    """
    assert (
        warnings_for(
            [
                ["연번", "서류명", "비고"],
                ["1", "입찰참가신청서", "소정양식"],
                ["2", "사업자등록증 사본", ""],
            ]
        )
        == []
    )


def test_clause_table_detection():
    clause = ExtractedTable(
        index=0, rows=[["조항", "항목", "요구조건"], ["2.1", "소비전력", "150 W 이하"]]
    )
    submission = ExtractedTable(
        index=0, rows=[["연번", "서류명", "비고"], ["1", "입찰참가신청서", "소정양식"]]
    )
    assert _is_clause_table(clause) is True
    assert _is_clause_table(submission) is False


def test_clean_clause_table_is_silent():
    """The real sample shape must stay warning-free."""
    assert (
        warnings_for(
            [
                ["조항", "항목", "요구조건"],
                ["3.1", "방수·방진 등급", "IP66 이상"],
                ["3.2", "본체 무게", "8 kg 이하"],
                ["3.3", "동작 온도범위", "-20℃ ~ 50℃"],
                ["3.4", "본체 재질", "알루미늄 다이캐스팅"],
            ]
        )
        == []
    )
