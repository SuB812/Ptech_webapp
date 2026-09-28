"""Phase 3: parent-child chunking.

This file decides whether TRAP-1, TRAP-3 and TRAP-4 are reachable at all. If the
equipment table is not chunked per row, no prompt can make clause 4.3 say
"found_absent"; if the sector heading is lost, clause 5.4 cannot be scoped; if
LT-200 is not tagged, the retriever cannot demote it.

No DB, no API key.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from common.enums import ChunkType
from knowledge.services.chunker import build_chunks, count_chunks
from knowledge.services.md_parse import parse_markdown_file

CATALOG = settings.SAMPLES_DIR / "03_자사_제품카탈로그.md"
QA = settings.SAMPLES_DIR / "04_자사_인증_시험_실적.md"


@pytest.fixture(scope="module")
def catalog_chunks():
    return build_chunks(parse_markdown_file(CATALOG))


@pytest.fixture(scope="module")
def qa_chunks():
    return build_chunks(parse_markdown_file(QA))


def all_children(parents):
    return [child for parent in parents for child in parent.children]


def find_child(parents, *needles):
    return [
        child
        for child in all_children(parents)
        if all(n in child.content for n in needles)
    ]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_one_table_one_parent(catalog_chunks, qa_chunks):
    """표 1개 = 부모 1개, 표는 절대 쪼개지 않는다."""
    catalog_tables = parse_markdown_file(CATALOG).tables
    qa_tables = parse_markdown_file(QA).tables

    catalog_table_parents = [p for p in catalog_chunks if p.chunk_type == ChunkType.TABLE]
    qa_table_parents = [p for p in qa_chunks if p.chunk_type == ChunkType.TABLE]

    assert len(catalog_table_parents) == len(catalog_tables) == 5
    assert len(qa_table_parents) == len(qa_tables) == 9


def test_table_row_count_matches_children(qa_chunks):
    """표 부모의 자식 수 = 표 본문 행 수."""
    doc = parse_markdown_file(QA)
    by_path = {}
    for table in doc.tables:
        by_path.setdefault(table.section_path, []).append(table)

    for parent in qa_chunks:
        if parent.chunk_type != ChunkType.TABLE:
            continue
        tables = by_path.get(parent.section_path, [])
        if len(tables) == 1:
            expected = len([r for r in tables[0].body if any(c.strip() for c in r)])
            assert len(parent.children) == expected, (
                f"{parent.section_path}: 자식 {len(parent.children)} != 행 {expected}"
            )


def test_all_parents_are_parents_and_children_are_not(catalog_chunks):
    assert all(p.is_parent for p in catalog_chunks)
    assert all(not c.is_parent for c in all_children(catalog_chunks))
    assert all(not c.children for c in all_children(catalog_chunks))


def test_every_chunk_has_a_section_path(catalog_chunks, qa_chunks):
    for parent in catalog_chunks + qa_chunks:
        assert parent.section_path
        for child in parent.children:
            assert child.section_path


def test_chunk_counts_are_in_a_sane_range(catalog_chunks, qa_chunks):
    """자릿수 확인용. 크게 벗어나면 청킹이 잘못된 것이다 (05 3.6절)."""
    cat_parents, cat_children = count_chunks(catalog_chunks)
    qa_parents, qa_children = count_chunks(qa_chunks)

    assert 8 <= cat_parents <= 16, f"카탈로그 부모 {cat_parents}"
    assert 25 <= cat_children <= 55, f"카탈로그 자식 {cat_children}"
    assert 10 <= qa_parents <= 20, f"QA 부모 {qa_parents}"
    assert 28 <= qa_children <= 70, f"QA 자식 {qa_children}"


def test_embedding_input_includes_section_path(catalog_chunks):
    """임베딩 입력에 헤딩 경로가 들어가야 LT-150 맥락이 벡터에 실린다."""
    child = find_child(catalog_chunks, "방수·방진 등급", "IP65")[0]
    text = child.embedding_input()
    assert child.section_path in text
    assert "LT-150" in text, "경로를 통해 모델명이 임베딩 입력에 들어가야 한다"
    assert child.content in text


# ---------------------------------------------------------------------------
# TRAP-4 — the equipment table
# ---------------------------------------------------------------------------


def test_equipment_rows_are_individual_children(qa_chunks):
    """09 §7.1 test_chunker_equipment_table — 가장 중요한 단정.

    이 표가 행 단위 자식으로 색인되지 않으면 `염수분무 시험` 검색이 0건이 되고
    조항 4.3 은 근거 없는 `not_found` 로만 남는다. TRAP-4 는 도달 불가가 된다.
    """
    salt = find_child(qa_chunks, "염수분무 시험기", "미보유")
    vibration = find_child(qa_chunks, "진동 시험기", "미보유")

    assert len(salt) == 1, f"염수분무 미보유 자식 청크 {len(salt)}개"
    assert len(vibration) == 1, f"진동 시험기 미보유 자식 청크 {len(vibration)}개"

    assert salt[0].chunk_type == ChunkType.TABLE_ROW
    assert "시험 설비" in salt[0].section_path


def test_equipment_we_do_have_is_also_chunked(qa_chunks):
    """'미보유' 가 실제 구분이 되려면 '보유' 행도 있어야 한다."""
    assert find_child(qa_chunks, "항온항습 챔버", "사내 보유")
    assert find_child(qa_chunks, "방수·방진 시험 챔버", "IP65까지")


# ---------------------------------------------------------------------------
# TRAP-3 — delivery records scoped by sector
# ---------------------------------------------------------------------------


def test_delivery_records_carry_their_sector(qa_chunks):
    """부문 헤딩이 section_path 에 남아야 LLM 이 집계 범위를 구분할 수 있다."""
    power = [c for c in all_children(qa_chunks) if "발전 부문" in c.section_path]
    industry = [c for c in all_children(qa_chunks) if "산업 부문" in c.section_path]
    public = [c for c in all_children(qa_chunks) if "공공 부문" in c.section_path]

    assert len(power) == 2, f"발전 부문 2건이어야 한다: {len(power)}"
    assert len(industry) == 5
    assert len(public) == 2

    orgs = " ".join(c.content for c in power)
    assert "한국남부발전" in orgs
    assert "한국서부발전" in orgs
    assert "포스코이앤씨" not in orgs, "산업 부문이 발전 부문으로 섞였다"


def test_record_rows_carry_the_sector_in_both_path_and_content(qa_chunks):
    """부문명이 경로와 내용 양쪽에 남는다.

    행 문장은 헤딩을 접두사로 붙이므로 (`4.1 발전 부문 — 계약연도: 2022, ...`)
    부문이 내용 자체에도 들어간다. 경로만 있을 때보다 강한 방어다 —
    LLM 이 부모 청크만 보더라도 집계 범위를 놓치지 않는다.
    """
    power = [c for c in all_children(qa_chunks) if "발전 부문" in c.section_path]
    assert len(power) == 2
    assert all("4.1 발전 부문" in c.section_path for c in power)
    assert all(c.content.startswith("4.1 발전 부문 —") for c in power), [
        c.content for c in power
    ]

    # 다른 부문 행이 발전 부문으로 새지 않는다.
    industry = [c for c in all_children(qa_chunks) if "산업 부문" in c.section_path]
    assert all("발전 부문" not in c.content for c in industry)


# ---------------------------------------------------------------------------
# TRAP-1 — model tagging
# ---------------------------------------------------------------------------


def test_lt200_section_is_tagged(catalog_chunks):
    """09 §7.1 test_chunker_model_tags."""
    lt200 = [c for c in all_children(catalog_chunks) if c.model_tags == ["LT-200"]]
    assert lt200, "LT-200 절 자식 청크에 model_tags 가 없다"

    values = " ".join(c.content for c in lt200)
    assert "195 W" in values
    assert "9.8 kg" in values


def test_lt150_section_is_tagged(catalog_chunks):
    lt150 = [c for c in all_children(catalog_chunks) if c.model_tags == ["LT-150"]]
    assert lt150

    ip65 = find_child(catalog_chunks, "방수·방진 등급", "IP65")
    assert ip65[0].model_tags == ["LT-150"]

    weight = find_child(catalog_chunks, "본체 무게", "7.2 kg")
    assert weight[0].model_tags == ["LT-150"]


def test_the_two_models_never_share_a_chunk(catalog_chunks):
    """195W 와 140W 가 같은 청크에 있으면 모델 필터가 무의미해진다."""
    for child in all_children(catalog_chunks):
        if "195 W" in child.content:
            assert "140 W" not in child.content
            assert child.model_tags == ["LT-200"]
        if "9.8 kg" in child.content:
            assert "7.2 kg" not in child.content


def test_supply_terms_are_model_agnostic(catalog_chunks):
    """납기 45일 / 보증 2년은 모델 무관이다.

    빈 model_tags 여야 한다. 태그가 붙으면 LT-150 쿼리에서 감점되어
    조항 5.3(보증)과 납기 교차검증의 근거가 사라진다.
    """
    warranty = [c for c in all_children(catalog_chunks) if "2년간" in c.content]
    lead_time = [c for c in all_children(catalog_chunks) if "45일" in c.content]

    assert warranty, "보증 2년 청크가 없다"
    assert lead_time, "납기 45일 청크가 없다"
    assert all(c.model_tags == [] for c in warranty), [c.model_tags for c in warranty]
    assert all(c.model_tags == [] for c in lead_time), [c.model_tags for c in lead_time]


def test_certifications_are_model_agnostic(qa_chunks):
    """인증은 회사 단위다. 모델 태그가 붙으면 안 된다."""
    ks = find_child(qa_chunks, "KSC-2022-1180")
    assert ks
    assert ks[0].model_tags == []


def test_test_reports_are_lt150(qa_chunks):
    """성적서 절 헤딩이 '(LT-150)' 이므로 성적서 행은 LT-150 소속이다."""
    report_rows = [
        c for c in all_children(qa_chunks) if "성적서 HB-T-2024-011" in c.section_path
    ]
    assert report_rows
    assert all("LT-150" in c.model_tags for c in report_rows)


# ---------------------------------------------------------------------------
# TRAP-2 — option side effects must survive into a chunk
# ---------------------------------------------------------------------------


def test_option_side_effects_are_chunked(catalog_chunks):
    """+1.4kg / +3주 가 검색 가능한 자식으로 남아야 한다."""
    option_row = find_child(catalog_chunks, "IP66 강화 하우징", "1.4kg")
    assert option_row, "IP66 선택사양 행 청크가 없다"
    assert "3주" in option_row[0].content

    narrative = find_child(catalog_chunks, "1.4kg 증가")
    assert narrative, "2.2 서술의 무게 증가 문장이 청크로 남지 않았다"


def test_extended_temperature_option_is_chunked(catalog_chunks):
    option = find_child(catalog_chunks, "확장 온도 사양")
    assert option
    assert "12%" in option[0].content
    assert "2주" in option[0].content


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def test_row_reads_as_a_sentence(catalog_chunks):
    """`| IP65 |` 같은 조각이 아니라 열 머리말이 붙은 문장이어야 한다."""
    child = find_child(catalog_chunks, "방수·방진 등급", "IP65")[0]
    assert child.content.startswith("2.2 구조 —"), child.content
    assert "항목:" in child.content or "방수·방진 등급:" in child.content


def test_parent_keeps_the_whole_table_as_markdown(catalog_chunks):
    parent = next(
        p for p in catalog_chunks
        if p.chunk_type == ChunkType.TABLE and "2.2 구조" in p.section_path
    )
    assert "| 방수·방진 등급 | IP65 |" in parent.content
    assert "| 본체 무게 | 7.2 kg |" in parent.content, "부모는 표 전체를 담아야 한다"
    assert "-20℃ ~ 45℃" in parent.content


def test_keywords_populated_on_children(catalog_chunks):
    child = find_child(catalog_chunks, "방수·방진 등급", "IP65")[0]
    assert "IP65" in child.keywords

    weight = find_child(catalog_chunks, "본체 무게", "7.2 kg")[0]
    assert "7.2KG" in weight.keywords
