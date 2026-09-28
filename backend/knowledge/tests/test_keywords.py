"""Phase 3: exact-match token extraction (09 §7.1 test_keyword_extraction)."""

from knowledge.services.keywords import extract_keywords, extract_models, normalize_token


def test_required_tokens_from_spec():
    """The four tokens specs/09 §7.1 names explicitly."""
    text = (
        "LT-150 방수·방진 등급 IP65, 성적서 HB-T-2024-011, 규격 KS C 7658"
    )
    tokens = extract_keywords(text)
    assert "LT-150" in tokens
    assert "IP65" in tokens
    assert "HB-T-2024-011" in tokens
    assert "KSC7658" in tokens, f"KS C 7658 정규화 실패: {tokens}"


def test_model_codes():
    assert extract_models("LT-150 과 LT-200 비교") == ["LT-150", "LT-200"]
    assert extract_models("모델 없음") == []


def test_ip_grades_are_distinguished():
    """IP65 와 IP66 은 서로 다른 토큰이어야 한다 — 판정을 가르는 한 글자다."""
    assert "IP65" in extract_keywords("방수·방진 등급: IP65")
    assert "IP66" in extract_keywords("IP66 강화 하우징")
    assert "IP66" not in extract_keywords("방수·방진 등급: IP65")


def test_certificate_and_document_numbers():
    tokens = extract_keywords(
        "KSC-2022-1180 / HE-2023-0471 / KC-2022-0885 / KSR-Q-2021-0339 / "
        "HB-CAT-2025-02 / HB-QA-2025-07 / HB-T-2023-046"
    )
    for expected in [
        "KSC-2022-1180", "HE-2023-0471", "KC-2022-0885", "KSR-Q-2021-0339",
        "HB-CAT-2025-02", "HB-QA-2025-07", "HB-T-2023-046",
    ]:
        assert expected in tokens, f"{expected} 누락: {tokens}"


def test_iso_standard():
    assert "ISO9001:2015" in extract_keywords("ISO 9001:2015 인증")


def test_units_with_thousand_separators():
    tokens = extract_keywords(
        "소비전력 140 W, 총 광속 21,500 lm, 광효율 153 lm/W, "
        "무게 7.2 kg, 수명 60,000 시간, 색온도 5,700 K"
    )
    assert "140W" in tokens
    assert "21500LM" in tokens, f"콤마 제거 실패: {tokens}"
    assert "153LM/W" in tokens
    assert "7.2KG" in tokens
    assert "60000시간" in tokens
    assert "5700K" in tokens


def test_normalization_is_symmetric():
    """색인과 쿼리가 같은 정규화를 거쳐야 배열 겹침이 동작한다."""
    indexed = extract_keywords("총 광속 21,500 lm")
    queried = extract_keywords("총 광속 (밝기) 20000lm 이상")
    assert "21500LM" in indexed
    assert "20000LM" in queried
    # 같은 값은 표기가 달라도 같은 토큰이 된다.
    assert normalize_token("20,000 lm") == normalize_token("20000LM") == "20000LM"


def test_requirement_text_yields_comparable_tokens():
    """사양서 요구조건에서도 같은 형태의 토큰이 나온다."""
    assert "IP66" in extract_keywords("IP66 이상")
    assert "8KG" in extract_keywords("8 kg 이하")
    assert "150W" in extract_keywords("150 W 이하")
    assert "KSC7658" in extract_keywords("KS C 7658")


def test_no_duplicates():
    """중복 토큰은 한 번만 남는다.

    순서는 텍스트 등장 순이 아니라 패턴 순이다 (구체적인 패턴이 먼저).
    배열 겹침 연산에는 순서가 무관하므로 문제되지 않는다.
    """
    tokens = extract_keywords("IP65 IP65 LT-150 IP65")
    assert tokens.count("IP65") == 1
    assert sorted(tokens) == ["IP65", "LT-150"]


def test_empty_and_none_safe():
    assert extract_keywords("") == []
    assert extract_keywords("", "설명만 있는 문장입니다.") == []
