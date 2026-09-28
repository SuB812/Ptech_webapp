"""Phase 1 acceptance: knowledge Markdown parsing.

Three things here are load-bearing for later phases, so each gets its own test:

* ``4.1 발전 부문`` must land in the heading path (TRAP-3 -- the model has to be
  able to count power-plant records only);
* the 시험 설비 table with ``염수분무 시험기 / 미보유`` must be parsed as a table
  (TRAP-4 -- this is the evidence that distinguishes "absent" from "not found");
* the LT-200 section must be separable from LT-150 (TRAP-1).

No DB, no API key.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.conf import settings

from knowledge.services.md_parse import parse_markdown_file

CATALOG = settings.SAMPLES_DIR / "03_자사_제품카탈로그.md"
QA = settings.SAMPLES_DIR / "04_자사_인증_시험_실적.md"


@pytest.fixture(scope="module")
def catalog():
    return parse_markdown_file(CATALOG)


@pytest.fixture(scope="module")
def qa():
    return parse_markdown_file(QA)


def test_sample_files_exist():
    assert CATALOG.exists(), f"자사 카탈로그가 없습니다: {CATALOG}"
    assert QA.exists(), f"자사 인증·시험·실적이 없습니다: {QA}"


# ---------------------------------------------------------------------------
# 제품 카탈로그 — specs/08-sample-data.md section 3
# ---------------------------------------------------------------------------


def test_catalog_metadata(catalog):
    assert catalog.title == "한빛조명(주) 제품 카탈로그"
    assert catalog.doc_no == "HB-CAT-2025-02"
    assert catalog.revision_date == date(2025, 5, 10)


def test_catalog_table_count(catalog):
    """2.1 성능, 2.2 구조, 2.3 선택사양, 3.1 성능, 3.2 구조 = 5개."""
    assert len(catalog.tables) == 5


def test_catalog_lt150_structure_table(catalog):
    """The IP65 / 7.2kg row -- the evidence for clauses 3.1 and 3.2."""
    tables = catalog.tables_under("2.2 구조")
    assert len(tables) == 1
    rows = dict((r[0], r[1]) for r in tables[0].body if len(r) >= 2)
    assert rows["방수·방진 등급"] == "IP65"
    assert rows["본체 무게"] == "7.2 kg"
    assert rows["동작 온도범위"] == "-20℃ ~ 45℃"
    assert rows["본체 재질"] == "알루미늄 다이캐스팅"


def test_catalog_lt150_performance_table(catalog):
    tables = catalog.tables_under("2.1 성능")
    assert len(tables) == 1
    rows = dict((r[0], r[1]) for r in tables[0].body if len(r) >= 2)
    assert rows["소비전력"] == "140 W"
    assert rows["총 광속"] == "21,500 lm"
    assert rows["광효율"] == "153 lm/W"
    assert rows["수명"] == "60,000 시간 (L70 기준)"


def test_catalog_option_side_effects_in_narrative(catalog):
    """TRAP-2 source data.

    The +1.4kg figure appears both in the 2.2 narrative and the 2.3 option
    table. The assessor needs at least one of them to emit ``side_effects``.
    """
    section = catalog.section("2.2 구조")
    assert section is not None
    assert "1.4kg 증가" in section.text
    assert "납기가 3주 추가" in section.text

    options = catalog.tables_under("2.3 선택사양")
    assert len(options) == 1
    option_rows = {r[0]: r[2] for r in options[0].body if len(r) >= 3}
    assert option_rows["IP66 강화 하우징"] == "무게 +1.4kg, 납기 +3주"
    assert option_rows["확장 온도 사양"] == "단가 +12%, 납기 +2주"


def test_catalog_lt200_is_separable(catalog):
    """TRAP-1 prerequisite.

    LT-200 (195W, 9.8kg) sits right next to LT-150. If the heading path does not
    carry the model name, the chunker cannot tag it and the retriever cannot
    penalise it.
    """
    lt200_tables = catalog.tables_under("LT-200")
    assert lt200_tables, "LT-200 절의 표를 헤딩 경로로 찾을 수 있어야 한다"

    values: dict[str, str] = {}
    for table in lt200_tables:
        values.update({r[0]: r[1] for r in table.body if len(r) >= 2})
    assert values["소비전력"] == "195 W"
    assert values["본체 무게"] == "9.8 kg"

    # And the model tag is derivable from the heading path alone.
    lt200_sections = [s for s in catalog.sections if s.model_tags == ["LT-200"]]
    assert lt200_sections, "LT-200 절에서 model_tags == ['LT-200'] 가 나와야 한다"

    lt150_sections = [s for s in catalog.sections if s.model_tags == ["LT-150"]]
    assert lt150_sections, "LT-150 절에서 model_tags == ['LT-150'] 가 나와야 한다"


def test_catalog_supply_terms_are_model_agnostic(catalog):
    """납기 45일 / 보증 2년 — evidence for 5.3 and the lead-time cross-check.

    These live under 4. 공급 조건, which names no model, so ``model_tags`` must be
    empty. A non-empty tag here would get this evidence penalised away.
    """
    warranty = catalog.section("4.2 보증")
    lead_time = catalog.section("4.1 납기")
    assert warranty is not None and lead_time is not None
    assert "2년간" in warranty.text
    assert "45일" in lead_time.text
    assert warranty.model_tags == []
    assert lead_time.model_tags == []


# ---------------------------------------------------------------------------
# 인증·시험·실적 — specs/08-sample-data.md section 4
# ---------------------------------------------------------------------------


def test_qa_metadata(qa):
    assert qa.title == "한빛조명(주) 인증·시험·실적 현황"
    assert qa.doc_no == "HB-QA-2025-07"
    assert qa.revision_date == date(2025, 6, 30)


def test_qa_table_count(qa):
    """인증 1 + 성적서 3 + 설비 1 + 실적 3 + 회사현황 1 = 9개."""
    assert len(qa.tables) == 9


def test_qa_certifications(qa):
    tables = qa.tables_under("1. 인증 보유 현황")
    assert len(tables) == 1
    certs = {r[0]: r[1] for r in tables[0].body if len(r) >= 2}
    assert certs["KS 인증 (KS C 7658)"] == "KSC-2022-1180"
    assert certs["고효율에너지기자재 인증"] == "HE-2023-0471"


def test_qa_equipment_table_is_parsed(qa):
    """TRAP-4 prerequisite -- the single most important assertion in this file.

    ``염수분무 시험기: 미보유`` is the evidence that makes clauses 4.3 and 4.4
    ``found_absent`` rather than ``not_found``. If this table is not parsed, the
    chunker cannot index it, the retriever cannot find it, and TRAP-4 is
    unreachable no matter how the prompt is written.
    """
    tables = qa.tables_under("3. 시험 설비 보유 현황")
    assert len(tables) == 1
    equipment = {r[0]: r[1] for r in tables[0].body if len(r) >= 2}

    assert equipment["염수분무 시험기"] == "미보유"
    assert equipment["진동 시험기"] == "미보유"
    # And the equipment we do have, so "미보유" is a real distinction.
    assert equipment["항온항습 챔버"] == "사내 보유"
    assert equipment["방수·방진 시험 챔버"] == "사내 보유 (IP65까지)"


def test_qa_delivery_records_split_by_sector(qa):
    """TRAP-3 prerequisite.

    9 records total, but only 2 are power-sector. The sector heading must be in
    the path or the model has no way to scope the count.
    """
    power = qa.tables_under("4.1 발전 부문")
    industry = qa.tables_under("4.2 산업 부문")
    public = qa.tables_under("4.3 공공 부문")

    assert len(power) == 1
    assert len(power[0].body) == 2, "발전 부문은 2건이다"
    assert len(industry[0].body) == 5, "산업 부문은 5건이다"
    assert len(public[0].body) == 2, "공공 부문은 2건이다"

    # The sector is recoverable from the table's own section path.
    assert "발전 부문" in power[0].section_path
    assert "산업 부문" not in power[0].section_path

    orgs = [r[1] for r in power[0].body]
    assert orgs == ["한국남부발전", "한국서부발전"]


def test_qa_test_reports(qa):
    """성적서 3건이 각각 별개 표로 나온다."""
    assert len(qa.tables_under("HB-T-2024-011")) == 1
    assert len(qa.tables_under("HB-T-2024-012")) == 1
    assert len(qa.tables_under("HB-T-2023-046")) == 1

    # HB-T-2024-012 tests to IP65, which is why clause 4.2 (IP66) is a gap.
    ip_table = qa.tables_under("HB-T-2024-012")[0]
    waterproof = [r for r in ip_table.body if "방수" in r[0]][0]
    assert waterproof[1] == "IP65"


def test_qa_test_reports_are_lt150(qa):
    """성적서 절은 LT-150 소속이다 (heading: '2. 시험성적서 보유 현황 (LT-150)')."""
    section = qa.section("HB-T-2024-011")
    assert section is not None
    assert "LT-150" in section.model_tags


# ---------------------------------------------------------------------------
# Structural guarantees the chunker relies on
# ---------------------------------------------------------------------------


def test_tables_are_never_split(catalog, qa):
    """Every table keeps a header plus at least one body row.

    Phase 3 makes one parent chunk per table; a split table would break that
    one-to-one mapping.
    """
    for doc in (catalog, qa):
        for table in doc.tables:
            assert len(table.rows) >= 2, f"{table.section_path} 표가 쪼개졌다"
            assert all(c == "" or c for c in table.header)


def test_horizontal_rules_are_not_tables(catalog):
    """``---`` separators in the source must not be read as table separators."""
    for table in catalog.tables:
        assert table.header != [""], "수평선을 표로 오인했다"
        assert len(table.header) >= 2


def test_every_table_has_a_section_path(catalog, qa):
    """No orphan tables. ``section_path`` becomes the Evidence location shown to users."""
    for doc in (catalog, qa):
        for table in doc.tables:
            assert table.heading_path, f"표 {table.index} 에 헤딩 경로가 없다"
            assert table.section_path.startswith("한빛조명(주)")
