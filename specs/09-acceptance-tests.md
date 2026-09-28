# 09. 인수 기준 — 정답표, 함정 시나리오, 정확도 측정

출처: `samples/00_실습가이드_정답표.md`. 이 문서가 PoC의 **합격/불합격 기준**이다.

> 이 PoC의 성공은 "잘 되네요"가 아니라 **"13개 중 11개 정확"** 처럼 숫자로 말할 수 있는
> 상태다. 숫자가 없으면 프롬프트를 고칠 근거도 없다.

---

## 1. 채점 대상 13개 항목

정답표는 총 13개 항목을 채점 대상으로 정의한다: **충족 7 + 보완 4 + 확인 필요 2**.
조항번호로 확정하면 다음 13개다.

```
2.1  2.2  2.3  2.4  2.5      (성능 5)
3.1  3.2  3.3  3.4           (구조 4)
4.3  4.4                     (시험 2)
5.3  5.4                     (품질보증 2)
```

`Requirement.is_graded=true` 는 이 13개에만 붙는다.

### 채점 제외 항목 (4건) — 참고용

원본 정답표는 `4.1`, `4.2` 를 다루지 않고, `5.1`·`5.2` 인증은 충족 표에 한 행으로 실려 있으나
"충족 7개"에는 포함되지 않는다 (7 + 4 + 2 = 13이 성립하는 조합은 위 13개뿐이다).
따라서 다음 4건은 **추출은 하되 채점하지 않는다.** 기대 판정은 참고로만 적는다.

| 조항 | 항목 | 기대 판정 | 근거 |
|---|---|---|---|
| 4.1 | 광속 및 광효율 측정 | 충족 | HB-T-2024-011 |
| 4.2 | 방수·방진 시험 (IP66) | 보완 | HB-T-2024-012의 기준이 IP65 |
| 5.1 | KS 인증 | 충족 | 인증현황 1절 `KSC-2022-1180` |
| 5.2 | 고효율에너지기자재 인증 | 충족 | 인증현황 1절 `HE-2023-0471` |

이 4건이 정답과 달라도 정확도 점수에는 반영하지 않는다. 단 정확도 패널의
`참고 항목` 섹션에 결과를 함께 보여준다.

---

## 2. 정답표

### 2.1 충족 (MEET) — 7개

| 조항 | 항목 | 요구 | 자사 | 근거 |
|---|---|---|---|---|
| 2.1 | 소비전력 | 150W 이하 | 140W | 카탈로그 2.1 |
| 2.2 | 총 광속 | 20,000lm 이상 | 21,500lm | 카탈로그 2.1, 성적서 HB-T-2024-011 |
| 2.3 | 광효율 | 140lm/W 이상 | 153lm/W | 성적서 HB-T-2024-011 |
| 2.4 | 색온도 | 5,700K | 5,700K | 카탈로그 2.1 |
| 2.5 | 수명 | 50,000h 이상 | 60,000h | 성적서 HB-T-2023-046 |
| 3.2 | 무게 | 8kg 이하 | 7.2kg | 카탈로그 2.2 |
| 3.4 | 본체 재질 | 알루미늄 다이캐스팅 | 동일 | 카탈로그 2.2 |

### 2.2 보완 필요 (GAP) — 4개

| 조항 | 항목 | 요구 | 자사 | 문제 |
|---|---|---|---|---|
| 3.1 | 방수등급 | IP66 이상 | IP65 | **한 등급 미달.** IP66 선택사양 있으나 무게 +1.4kg → 8.6kg가 되어 조항 3.2 위반 |
| 3.3 | 동작온도 | -20 ~ 50℃ | -20 ~ 45℃ | **상한 5℃ 부족.** 확장 온도 선택사양(-30~55℃)으로 해결 가능, 단가 +12% |
| 5.3 | 보증기간 | 3년 이상 | 2년 | 1년 부족 |
| 5.4 | 납품실적 | 발전소 3건 이상 | 2건 | 남부발전 2022, 서부발전 2024만 해당 |

### 2.3 확인 필요 (CHECK) — 2개

| 조항 | 항목 | 사유 |
|---|---|---|
| 4.3 | 내염수분무 시험 | 성적서 없음. 설비 현황에 `염수분무 시험기: 미보유` 명시 |
| 4.4 | 내진동 시험 | 성적서 없음. `진동 시험기: 미보유` |

두 항목 모두 `evidence_state = found_absent` 여야 한다. `not_found`(검색 실패)로 나오면
판정은 맞지만 **함정 4는 실패**로 기록한다 (3.4절 참조).

---

## 3. 함정 4개 — 테스트 시나리오

AI가 이걸 잡아내는지 보면 성능 차이가 드러난다. 각 함정은 통과/실패를 기계적으로 판정한다.

---

### TRAP-1 — 모델 혼동

**심어둔 것**: 카탈로그에 LT-150(140W, 7.2kg)과 LT-200(195W, 9.8kg)이 나란히 있다.
공고 품목은 `LED 투광등 150W급` 이므로 LT-150이 맞다.

**오답의 모습**: `2.1 소비전력` 에 LT-200의 195W를 가져와 `150W 이하` 위반 → 보완 필요.
`3.2 무게` 에 9.8kg를 가져와 `8kg 이하` 위반 → 보완 필요.
즉 충족이던 두 항목이 뒤집힌다.

**통과 조건 (전부 만족)**
1. `2.1` 의 `ai_verdict == MEET` 이고 `ai_our_value` 에 `140` 이 포함된다 (`195` 불포함).
2. `3.2` 의 `ai_verdict == MEET` 이고 `ai_our_value` 에 `7.2` 가 포함된다 (`9.8` 불포함).
3. `2.1`·`3.2`·`2.2`·`2.3`·`2.5` 의 `Evidence` 중 `model_tags` 에 `LT-200` 만 있는 청크가
   `rank == 1` 로 인용되지 않는다.

**방어 장치**
- `KnowledgeChunk.model_tags` (`03-data-model.md` 4절)
- 검색 단계 모델 필터 + 불일치 ×0.3 감점 (`05-rag-pipeline.md` 5.3-5)
- 판정 프롬프트 절대 규칙 3 (`06-analysis-pipeline.md` 3.3)

**실패 시 조치**: 재랭크(모델 필터) 효과를 데모에서 보여주는 지점이다. 모델 필터를 끄고
한 번, 켜고 한 번 실행해 차이를 나란히 보여준다.

---

### TRAP-2 — 선택사양의 연쇄 효과 (가장 어려움)

**심어둔 것**: `3.1` 의 IP66을 선택사양으로 맞추면 무게가 7.2 + 1.4 = **8.6kg** 이 되어
`3.2` 의 8kg 제한을 넘는다. 두 조항을 동시에 만족하는 조합이 없다.

**왜 어려운가**: 항목별로 독립 판정하는 구조에서는 **절대 못 잡는다.**
`3.1` 판정 시엔 3.2를 모르고, `3.2` 판정 시엔 표준 무게 7.2kg만 보므로 각각 맞는 판정이
나오지만 합치면 모순이다. RAG의 구조적 한계와 사람 검토가 필요한 이유를 설명하는 지점이다.

**통과 조건 (전부 만족)**
1. `3.1` 의 `ai_verdict == GAP` (선택사양이 있다고 `MEET` 로 처리하지 않는다).
2. `3.1` 의 `remedy_side_effects` 에 `{field:"weight", value:1.4, unit:"kg"}` 가 있다.
3. `CrossClauseIssue` 중 `clause_nos` 가 `{"3.1","3.2"}` 인 이슈가 1건 이상 존재하고
   `severity == "high"` 이며 `description` 에 `8.6` 이 포함된다.

**방어 장치**
- 판정 프롬프트 절대 규칙 4 — 선택사양은 `MEET` 가 아니라 `remedy` + `side_effects`
- `Assessment.remedy_side_effects` 필드
- **교차조항 검증 별도 패스** (`06-analysis-pipeline.md` 5절) — 이것 없이는 통과 불가

**추가 확인 (필수는 아니나 검출되면 좋다)**: 납기 상충.
표준 45일 + IP66 3주(21일) + 확장온도 2주(14일) = 80일 > 공고 60일.
IP66만 적용해도 45 + 21 = 66일 > 60일이다. `medium` 이상 이슈로 검출되면 가점.

---

### TRAP-3 — 실적 분류

**심어둔 것**: `5.4` 는 **발전소 실적만** 센다. 실적표에는 산업 5건, 공공 2건이 더 있어
총 9건이지만 발전 부문은 2건뿐이다.

**오답의 모습**: "9건 보유, 충족". 또는 "2024 서부발전은 LT-200이므로 제외, 1건" 같은
과도한 축소 (품목 모델은 실적 인정 조건이 아니다 — 공고는 발전소 납품실적만 요구한다).

**통과 조건 (전부 만족)**
1. `5.4` 의 `ai_verdict == GAP`.
2. `ai_our_value` 또는 `rationale` 에 `2건` 이 포함된다.
3. `rationale` 에 `9건` 을 근거로 충족을 주장하는 서술이 없다.
4. `rationale` 에 세는 범위를 밝힌 서술이 있다 (`발전`, `부문`, `제외` 중 하나 이상 포함).

**방어 장치**
- 청킹 시 부문 헤딩(`4.1 발전 부문`)을 `section_path` 에 포함 (`05-rag-pipeline.md` 3.3)
- 판정 프롬프트 절대 규칙 5 — 범위 한정 집계, 무엇을 세고 제외했는지 명시

**참고**: 공고문 `3.3` (참가자격)도 같은 요구다. 채점 대상은 `5.4` 이지만
`공고 3.3` 도 같은 판정이 나와야 일관성이 있다. 불일치 시 경고를 띄운다.

---

### TRAP-4 — 시험 항목의 부재 확인

**심어둔 것**: `4.3`·`4.4` 는 **"없다"는 것을 판정**해야 한다.
검색해서 안 나온 것과, 실제로 없는 것을 구분해야 한다. 설비 현황표에
`염수분무 시험기: 미보유`, `진동 시험기: 미보유` 라고 명시해 두었으므로
**제대로 검색하면 근거를 찾을 수 있다.** 여기까지 짚으면 잘 되는 것이다.

**오답의 모습 3가지**
1. 유사한 다른 성적서(HB-T-2024-012 방수시험)를 근거로 `MEET` 판정.
2. `CHECK` 는 맞췄으나 `evidence_state == not_found` — 즉 "검색이 안 됐다"로만 처리.
   판정은 맞지만 근거를 제시하지 못하므로 기술질의서 문안의 품질이 떨어진다.
3. 근거 없이 "성적서가 없을 것으로 추정" 같은 환각.

**통과 조건 (전부 만족)**
1. `4.3`·`4.4` 모두 `ai_verdict == CHECK`.
2. `4.3`·`4.4` 모두 `evidence_state == found_absent` (`not_found` 가 아니다).
3. `4.3` 의 `Evidence` 중 `content` 에 `염수분무 시험기` 와 `미보유` 가 함께 있는 청크가 있다.
4. `4.4` 의 `Evidence` 중 `content` 에 `진동 시험기` 와 `미보유` 가 함께 있는 청크가 있다.

**방어 장치**
- 설비 현황표를 **행 단위 자식 청크**로 색인 (`05-rag-pipeline.md` 3.2)
- `EvidenceState.FOUND_ABSENT` enum
- 판정 프롬프트 절대 규칙 1, 6

**선행 확인**: `POST /api/knowledge/search/` 로 `염수분무 시험` 을 검색해
`염수분무 시험기: 미보유` 가 상위에 나오는지 먼저 확인한다. 여기서 안 나오면
TRAP-4는 통과할 수 없다. 이것이 FR-12 검색 테스트 화면의 존재 이유다.

---

## 4. `answer_key.json` 형식

경로: `backend/analysis/fixtures/answer_key.json`

```json
{
  "source": "samples/00_실습가이드_정답표.md",
  "project_hint": { "bid_no": "KPG-2025-EQ-0417", "spec_doc_no": "KPG-2025-TS-0417" },
  "graded_total": 13,
  "items": [
    { "clause_no": "2.1", "item": "소비전력", "requirement": "150W 이하",
      "expected_verdict": "MEET", "expected_our_value_contains": ["140"],
      "forbidden_our_value_contains": ["195"],
      "expected_evidence_keywords": ["140"],
      "evidence_hint": "카탈로그 2.1" },
    { "clause_no": "2.2", "item": "총 광속", "requirement": "20,000lm 이상",
      "expected_verdict": "MEET", "expected_our_value_contains": ["21,500", "21500"],
      "evidence_hint": "카탈로그 2.1, 성적서 HB-T-2024-011" },
    { "clause_no": "2.3", "item": "광효율", "requirement": "140lm/W 이상",
      "expected_verdict": "MEET", "expected_our_value_contains": ["153"],
      "evidence_hint": "성적서 HB-T-2024-011" },
    { "clause_no": "2.4", "item": "색온도", "requirement": "5,700K",
      "expected_verdict": "MEET", "expected_our_value_contains": ["5,700", "5700"],
      "evidence_hint": "카탈로그 2.1" },
    { "clause_no": "2.5", "item": "수명", "requirement": "50,000h 이상",
      "expected_verdict": "MEET", "expected_our_value_contains": ["60,000", "60000"],
      "evidence_hint": "성적서 HB-T-2023-046" },
    { "clause_no": "3.1", "item": "방수등급", "requirement": "IP66 이상",
      "expected_verdict": "GAP", "expected_our_value_contains": ["IP65"],
      "expected_side_effect_fields": ["weight"],
      "evidence_hint": "카탈로그 2.2" },
    { "clause_no": "3.2", "item": "무게", "requirement": "8kg 이하",
      "expected_verdict": "MEET", "expected_our_value_contains": ["7.2"],
      "forbidden_our_value_contains": ["9.8"],
      "evidence_hint": "카탈로그 2.2" },
    { "clause_no": "3.3", "item": "동작온도", "requirement": "-20 ~ 50℃",
      "expected_verdict": "GAP", "expected_our_value_contains": ["45"],
      "evidence_hint": "카탈로그 2.2" },
    { "clause_no": "3.4", "item": "본체 재질", "requirement": "알루미늄 다이캐스팅",
      "expected_verdict": "MEET", "expected_our_value_contains": ["알루미늄"],
      "evidence_hint": "카탈로그 2.2" },
    { "clause_no": "4.3", "item": "내염수분무 시험", "requirement": "염해 환경 대응, 240시간",
      "expected_verdict": "CHECK", "expected_evidence_state": "found_absent",
      "expected_evidence_keywords": ["염수분무 시험기", "미보유"],
      "evidence_hint": "QA 3절 시험 설비 보유 현황" },
    { "clause_no": "4.4", "item": "내진동 시험", "requirement": "KS C 7658",
      "expected_verdict": "CHECK", "expected_evidence_state": "found_absent",
      "expected_evidence_keywords": ["진동 시험기", "미보유"],
      "evidence_hint": "QA 3절 시험 설비 보유 현황" },
    { "clause_no": "5.3", "item": "보증기간", "requirement": "3년 이상",
      "expected_verdict": "GAP", "expected_our_value_contains": ["2년", "2"],
      "evidence_hint": "카탈로그 4.2" },
    { "clause_no": "5.4", "item": "납품실적", "requirement": "발전소 3건 이상",
      "expected_verdict": "GAP", "expected_our_value_contains": ["2건", "2"],
      "forbidden_rationale_contains": ["9건 보유"],
      "expected_rationale_any_of": ["발전", "부문", "제외"],
      "evidence_hint": "QA 4.1 발전 부문" }
  ],
  "reference_items": [
    { "clause_no": "4.1", "expected_verdict": "MEET", "graded": false },
    { "clause_no": "4.2", "expected_verdict": "GAP",  "graded": false },
    { "clause_no": "5.1", "expected_verdict": "MEET", "graded": false },
    { "clause_no": "5.2", "expected_verdict": "MEET", "graded": false }
  ],
  "traps": [
    { "id": "TRAP-1", "name": "모델 혼동",
      "checks": [
        { "kind": "verdict",  "clause_no": "2.1", "equals": "MEET" },
        { "kind": "our_value","clause_no": "2.1", "contains": "140", "not_contains": "195" },
        { "kind": "verdict",  "clause_no": "3.2", "equals": "MEET" },
        { "kind": "our_value","clause_no": "3.2", "contains": "7.2", "not_contains": "9.8" },
        { "kind": "no_top_evidence_model", "clause_nos": ["2.1","2.2","2.3","2.5","3.2"],
          "model": "LT-200" } ] },
    { "id": "TRAP-2", "name": "선택사양 연쇄 효과",
      "checks": [
        { "kind": "verdict", "clause_no": "3.1", "equals": "GAP" },
        { "kind": "side_effect", "clause_no": "3.1", "field": "weight", "value": 1.4 },
        { "kind": "cross_issue", "clause_nos": ["3.1","3.2"],
          "severity": "high", "description_contains": "8.6" } ] },
    { "id": "TRAP-3", "name": "실적 분류",
      "checks": [
        { "kind": "verdict", "clause_no": "5.4", "equals": "GAP" },
        { "kind": "text", "clause_no": "5.4", "field": "rationale_or_our_value",
          "contains": "2건" },
        { "kind": "text", "clause_no": "5.4", "field": "rationale",
          "not_contains": "9건 보유" },
        { "kind": "text_any", "clause_no": "5.4", "field": "rationale",
          "any_of": ["발전", "부문", "제외"] } ] },
    { "id": "TRAP-4", "name": "시험 부재 확인",
      "checks": [
        { "kind": "verdict", "clause_no": "4.3", "equals": "CHECK" },
        { "kind": "verdict", "clause_no": "4.4", "equals": "CHECK" },
        { "kind": "evidence_state", "clause_no": "4.3", "equals": "found_absent" },
        { "kind": "evidence_state", "clause_no": "4.4", "equals": "found_absent" },
        { "kind": "evidence_contains", "clause_no": "4.3",
          "all_of": ["염수분무 시험기", "미보유"] },
        { "kind": "evidence_contains", "clause_no": "4.4",
          "all_of": ["진동 시험기", "미보유"] } ] }
  ]
}
```

`evaluator.py` 규칙:
- **점수는 `expected_verdict` vs `ai_verdict` 일치만으로 계산한다.** 13점 만점.
- `expected_our_value_contains` 등 나머지 필드는 함정 판정과 오답 원인 분석에 쓴다.
  점수에 반영하지 않는다 (판정은 맞고 값 표기만 다른 경우를 오답으로 세면 측정이 왜곡된다).
- 값 비교 시 콤마와 공백을 제거하고 비교한다 (`21,500` == `21500`).
- `clause_no` 로 매칭한다. 해당 조항의 `Assessment` 가 없으면 오답 처리하고
  `mismatches` 에 `"추출되지 않음"` 을 기록한다.

---

## 5. 정확도 리포트 (FR-24 출력)

```
정확도: 11 / 13 (84.6%)

판정별
  충족(MEET)      기대 7  정답 6
  보완(GAP)       기대 4  정답 3
  확인필요(CHECK) 기대 2  정답 2

혼동
  기대 GAP  → 실제 MEET : 1건
  기대 MEET → 실제 GAP  : 1건

오답 상세
  5.4 납품실적    기대 GAP  실제 MEET   "총 9건 보유"     → 함정 3 미통과
  3.2 무게        기대 MEET 실제 GAP    "9.8kg"          → 함정 1 미통과

함정
  TRAP-1 모델 혼동          X   3.2 our_value 에 9.8 포함
  TRAP-2 선택사양 연쇄 효과   O
  TRAP-3 실적 분류          X   rationale 에 "9건 보유" 포함
  TRAP-4 시험 부재 확인      O

참고 항목 (채점 제외)
  4.1 O   4.2 O   5.1 O   5.2 O
```

---

## 6. 합격 기준

| 기준 | 최소 | 목표 |
|---|---|---|
| 요구사항 추출 | 17개 조항 전부 | + 공고 참가자격 3건 |
| 판정 정확도 | **10 / 13** | **13 / 13** |
| 함정 통과 | TRAP-1, TRAP-3, TRAP-4 (3개) | 4개 전부 |
| 근거 제시율 | `MEET`/`GAP` 항목 100%에 근거 1건 이상 | |
| 근거 없는 MEET | **0건** (원칙 3 — 위반 시 무조건 불합격) | |
| 전체 실행 시간 | 3분 이내 | 2분 이내 |
| 산출물 | 대응표·체크리스트·기술질의서 생성 + Excel 다운로드 | |

TRAP-2는 교차조항 검증 패스가 동작해야 통과한다. 최소 기준에서 제외한 이유는
이것이 파이프라인 구조에 가장 의존적이고, 데모에서는 "RAG의 한계"를 설명하는 소재로도
쓸 수 있기 때문이다. 다만 구현 목표에는 포함된다.

---

## 7. 자동화 테스트

### 7.1 LLM 없는 테스트 (`LLM_FAKE=True`, CI 가능)

| 테스트 | 검증 |
|---|---|
| `test_pdf_extract_tables` | 샘플 사양서에서 표 4개, `['2.1','소비전력','150 W 이하']` 행이 정확히 나온다 |
| `test_pdf_extract_announcement` | 샘플 공고문에서 표 3개, 제출서류 8행 |
| `test_chunker_parent_child` | 표 1개 = 부모 1개, 행 수 = 자식 수 |
| `test_chunker_model_tags` | LT-200 절 청크의 `model_tags == ["LT-200"]` |
| `test_chunker_equipment_table` | `염수분무 시험기: 미보유` 가 자식 청크로 존재 |
| `test_keyword_extraction` | `IP65`, `LT-150`, `HB-T-2024-011`, `KS C 7658` 추출 |
| `test_retriever_keyword_exact` | `IP66` 쿼리에서 `IP66` 청크가 `IP65` 청크보다 높은 점수 |
| `test_retriever_model_filter` | `model_filter="LT-150"` 시 LT-200 청크가 감점된다 |
| `test_meet_without_evidence_rejected` | 근거 0건 + `MEET` 저장 시 `CHECK` 로 강제 |
| `test_meet_without_evidence_api` | `PATCH` 로 `MEET` 설정 시 `400 meet_without_evidence` |
| `test_cross_clause_weight_conflict` | 3.1 side_effect + 3.2 제약 → `8.6kg > 8kg` 이슈 생성 |
| `test_cross_clause_lead_time` | 45 + 21 = 66일 > 60일 이슈 생성 |
| `test_knowledge_rejects_bid_doc` | 공고문 업로드 시 `400 knowledge_doc_type_forbidden` |
| `test_source_doc_never_indexed` | `SourceDocument` 업로드 후 `KnowledgeChunk` 증가 없음 |
| `test_evaluator_scoring` | 조작한 `Assessment` 집합으로 점수·혼동표·함정 판정 검증 |
| `test_clause_no_sorting` | `2.10` 이 `2.2` 뒤로 정렬된다 |
| `test_xlsx_export_sheets` | 시트 3개, 헤더 행 일치 |

### 7.2 LLM 있는 테스트 (수동 실행, `pytest -m llm`)

| 테스트 | 검증 |
|---|---|
| `test_extract_17_clauses` | 샘플 사양서에서 17개 조항 추출 |
| `test_full_pipeline_accuracy` | 전체 실행 후 정확도 >= 10/13 |
| `test_traps` | TRAP-1, 3, 4 통과 |
| `test_inquiry_covers_check_items` | 4.3, 4.4 질의 문안 생성 |

CI에서는 7.1만 돌린다. 7.2는 프롬프트를 바꿀 때마다 수동으로 돌리고 결과를 8절에 기록한다.

---

## 8. 정확도 측정 기록

프롬프트나 RAG 파라미터를 바꿀 때마다 한 줄 추가한다. **비워두지 말 것** —
이 표가 없으면 개선했는지 악화했는지 말할 수 없다. `README.md` 에도 최신 결과를 반영한다.

| 날짜 | 모델 | 프롬프트 버전 | RAG 파라미터 | 정확도 | TRAP 1/2/3/4 | 메모 |
|---|---|---|---|---|---|---|
| | | | | / 13 | | 첫 측정 전 |

---

## 9. 실습/데모 진행 순서

원본 가이드 7절을 이 시스템에 맞춰 옮긴 것. 데모 시연 시 이 순서로 보여준다.

1. **지식 2건 업로드** → 검색 테스트 화면에서 `방수 등급`, `발전소 납품실적`,
   `염수분무 시험` 세 개를 던져 본다. 세 번째가 특히 볼 만하다. 청킹 방식에 따라
   설비 현황표가 잡히기도 하고 안 잡히기도 한다.
2. **입찰 건 생성 + 공고문·사양서 업로드** → 추출 결과 표를 원본과 나란히 보여준다.
3. **요구사항 추출만 먼저 실행** → 17개 조항 JSON이 제대로 나오는지 확인한다.
4. **분석 실행** (반복 검색 + 판정) → 진행률이 올라가는 것을 보여준다.
5. **정답표와 대조해 정확도 측정** — 여기가 핵심이다.
   "잘 되네요" 대신 "13개 중 11개 정확"이라고 말할 수 있어야 프롬프트를 고칠 근거가 생긴다.
6. **함정 4개를 하나씩 짚는다.** 특히 TRAP-2로 "항목별 독립 판정의 구조적 한계와
   사람 검토가 필요한 이유"를 설명한다.
7. **프롬프트 개선 후 재측정** → 8절 표에 기록한다.
