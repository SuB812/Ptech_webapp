# 06. 분석 파이프라인 — 추출, 항목별 판정, 교차검증, 취합

## 0. 전체 흐름

```
[1] 입력 문서 업로드 (공고문 + 기술사양서 PDF)
      │  pdfplumber → DocumentPage(text, tables)
      ▼
[2] LLM ① 요구사항 추출 → JSON 배열 [{clause_no, category, item, requirement_text}, ...]
      │  + 제출서류 / 참가자격 / 기본정보 추출
      ▼
   ── 사람 검토 (FR-07) ──   요구사항 확인·수정·채점대상 지정
      ▼
[3] 반복 (요구사항 개수만큼, 한 건씩):
      ├─ 하이브리드 검색 (쿼리 = item + requirement_text + 모델명)
      └─ LLM ② 대조 판정 → {verdict, our_value, rationale, remedy, side_effects}
      ▼
[4] 검증: 근거 0건 + MEET → CHECK 로 강제
      ▼
[5] 교차조항 검증 (별도 패스) → CrossClauseIssue
      ▼
[6] LLM ③ 취합 → 대응표 + 체크리스트 + 기술질의서 초안
      ▼
[7] 정확도 측정 (정답표 대조)
```

**3단계의 반복이 이 시스템의 핵심이다.** 요구사항 17개를 한 번에 검색하면 벡터가 뭉개져
아무것도 못 찾는다. 항목 하나씩 따로 검색한다.

---

## 1. 1단계 — 문서 추출

`specs/05-rag-pipeline.md` 2절 참조. 결과물은 `DocumentPage.text` 와 `DocumentPage.tables`.

---

## 2. 2단계 — 요구사항 추출 (LLM ①)

### 2.1 입력 구성

프롬프트에 넣는 것:
- 문서 종류 (`announcement` / `techspec`), 문서번호
- 페이지별 본문 텍스트
- 페이지별 표를 **Markdown 표로 직렬화**한 것 (2차원 배열 그대로 넣지 않는다 — LLM이
  Markdown 표를 훨씬 안정적으로 읽는다)
- 허용 `category` 값 목록 (FR-06)

### 2.2 프롬프트 — `analysis/prompts/extract_requirements.txt`

```
당신은 발전소 기자재 입찰의 기술영업 담당자다. 아래 발주처 문서에서 입찰자가
충족해야 하는 요구조건을 빠짐없이 추출한다.

# 규칙
1. 표에 있는 조항은 표의 행 하나가 요구사항 하나다. 행을 합치거나 나누지 않는다.
2. 조항번호(clause_no)는 문서에 적힌 그대로 쓴다. 표에 조항 열이 없으면
   출처를 붙여 "공고 3.3" 처럼 쓴다.
3. 표 밖의 서술 문장이 특정 조항의 조건을 보충하면 그 조항의 context_text 에 넣는다.
   예: "설치 장소는 해안에서 약 2km 거리" 는 방수 등급 조항의 context_text 다.
4. 요구조건(requirement_text)은 원문 표기를 유지한다. 단위를 바꾸거나 반올림하지 않는다.
   "150 W 이하" 를 "150W" 로 줄이지 않는다.
5. 값을 추측하지 않는다. 표의 칸이 비어 있으면 requirement_text 를 빈 문자열로 두고
   warnings 에 그 조항번호를 적는다.
6. category 는 다음 값 중 하나만 쓴다: {allowed_categories}
7. 요구사항이 아닌 것은 넣지 않는다: 문의 전화번호, 인사말, 목차, 페이지 번호.

# 문서 정보
문서 종류: {doc_type_label}
문서번호: {doc_no}

# 본문
{body_text}

# 표
{tables_markdown}

# 출력
아래 JSON만 출력한다. 설명을 덧붙이지 않는다.
{{
  "requirements": [
    {{ "clause_no": "2.1", "chapter": "제2장 성능 요구사항", "category": "efficiency",
       "item": "소비전력", "requirement_text": "150 W 이하",
       "context_text": "", "source_page": 1 }}
  ],
  "submission_items": [
    {{ "seq": 1, "name": "입찰참가신청서", "note": "소정양식" }}
  ],
  "participation_reqs": [
    {{ "seq": "3.1", "text": "LED 조명 제조업 등록을 필한 자" }}
  ],
  "bid_info": {{
    "title": "", "bid_no": "", "org": "", "item_name": "", "quantity": "",
    "estimated_price": "", "delivery_place": "", "delivery_term": "",
    "announced_on": "", "inquiry_due_at": "", "bid_due_at": "", "opening_at": "",
    "spec_doc_no": ""
  }},
  "warnings": []
}}
```

### 2.3 후처리

- `category` 가 허용 목록 밖이면 `other` 로 강제.
- `clause_no` 중복 시 `item` 으로 구분, 완전 중복이면 뒤를 버리고 경고.
- `order` 는 `clause_no` 를 숫자 튜플로 파싱해 정렬한 순서로 부여.
- 날짜 문자열은 `YYYY-MM-DD` / `YYYY-MM-DD HH:MM` 만 허용. 파싱 실패 시 `null` + 경고.
- 샘플 기준 **17개 조항** (2.1~2.5, 3.1~3.4, 4.1~4.4, 5.1~5.4) 이 나와야 한다.
  개수가 다르면 경고를 띄운다 (하드 실패는 아니다 — 다른 입찰 건은 조항 수가 다르다).

### 2.4 채점 대상 자동 지정

추출 직후, `answer_key.json` 에 있는 `clause_no` 와 일치하는 요구사항에
`is_graded=true` 를 설정한다. 이것은 **테스트 편의 기능**이며 판정 로직에
정답을 노출하지 않는다 (`is_graded` 는 프롬프트에 들어가지 않는다).

---

## 3. 3단계 — 항목별 검색 및 판정 (반복, LLM ②)

활성 요구사항(`is_active=true`)을 `order` 순으로 **한 건씩** 처리한다.

### 3.1 검색 쿼리 생성

```python
def build_query(req, project) -> str:
    parts = [req.item, req.requirement_text]
    if req.context_text:
        parts.append(req.context_text[:120])
    model = extract_model_hint(project.item_name)   # "LED 투광등 150W급" → "LT-150"
    if model:
        parts.append(model)
    return " ".join(p for p in parts if p)
```

`extract_model_hint` 는 자사 모델 라인업과 공고 품목을 맞춘다. `150W급` → 소비전력 150W대
모델 → `LT-150`. 매칭 규칙은 지식베이스의 `model_tags` 목록과 공고 `item_name` 의
숫자를 비교해 결정한다. 확신이 없으면 `None` 을 반환하고 모델 필터를 걸지 않는다
(잘못된 필터가 근거를 지우는 것보다 낫다).

예시 쿼리:
- `2.1` → `소비전력 150 W 이하 LT-150`
- `3.1` → `방수·방진 등급 IP66 이상 설치 장소가 옥외 해안 인근이므로... LT-150`
- `4.3` → `내염수분무 시험 염해 환경 대응, 240시간 LT-150`
- `5.4` → `납품실적 최근 5년 발전소 납품실적 3건 이상 LT-150`

### 3.2 검색 호출

```python
hits = retriever.search(query, top_k=run.rag_params["top_k"],
                        threshold=run.rag_params["threshold"],
                        w_semantic=..., w_keyword=...,
                        model_filter=model)
```

`retrieval_query` 와 `retrieved_chunk_ids` 를 `Assessment` 에 저장해 재현 가능하게 한다.

### 3.3 판정 프롬프트 — `analysis/prompts/assess_requirement.txt`

LLM에 전달하는 근거는 **부모 청크 전문**이다 (자식이 아니라). 같은 부모의 자식이
여러 건 걸리면 부모를 한 번만 넣는다.

```
당신은 발전소 기자재 입찰의 기술 검토자다. 발주처 요구조건 하나와 자사 자료에서
검색된 근거를 대조해 판정한다.

# 판정 기준 (반드시 이 중 하나)
- MEET  (충족): 근거가 요구조건을 만족함을 명확히 보여준다.
- GAP   (보완 필요): 근거를 찾았고, 자사 값이 요구조건에 미달한다.
- CHECK (확인 필요): 근거가 없다. 또는 자사 자료에 해당 항목이 없거나 "미보유"로
         명시되어 있다. 또는 근거가 요구조건과 같은 대상인지 확신할 수 없다.

# 절대 규칙
1. 근거가 비어 있으면 무조건 CHECK 다. MEET 를 쓸 수 없다.
2. 근거에 없는 값을 지어내지 않는다. 일반 상식이나 업계 통념으로 보충하지 않는다.
3. 근거가 다른 제품 모델의 값이면 MEET 로 쓰지 않는다. 요구 품목은 {model_hint} 이다.
   근거의 모델이 다르면 CHECK 로 판정하고 그 사실을 rationale 에 적는다.
4. "요구조건을 만족하는 선택사양이 있다"는 것은 MEET 가 아니다. 표준 사양이 미달하면
   GAP 이고, 선택사양은 remedy 에 적는다. 선택사양의 부작용(무게·단가·납기 변화)은
   근거에 적힌 수치 그대로 side_effects 에 넣는다.
5. 개수를 세는 요구조건(예: 실적 3건 이상)은 요구조건이 한정하는 범위만 센다.
   범위 밖의 항목을 합산하지 않는다. 무엇을 세었고 무엇을 제외했는지 rationale 에 적는다.
6. 시험·성적서 요구는 해당 시험의 성적서가 근거에 있어야 MEET 다. 유사한 다른 시험의
   성적서로 대체 판정하지 않는다.
7. our_value 는 근거에서 인용한 자사 값만 쓴다. 없으면 빈 문자열이다.

# 발주처 요구조건
조항: {clause_no}
분류: {category_label}
항목: {item}
요구조건: {requirement_text}
관련 서술: {context_text}

# 자사 자료 검색 근거 ({evidence_count}건)
{evidence_blocks}

# 출력
아래 JSON만 출력한다.
{{
  "verdict": "MEET | GAP | CHECK",
  "evidence_state": "found_sufficient | found_insufficient | found_absent | not_found",
  "our_value": "",
  "rationale": "판정 근거를 2~3문장으로. 어느 문서 어느 절을 봤는지 포함한다.",
  "gap_detail": "GAP 일 때만. 무엇이 얼마나 미달인지.",
  "remedy": "대체방안이 근거에 있을 때만.",
  "side_effects": [
    {{ "field": "weight | price | lead_time | temperature | other",
       "op": "add | multiply | replace", "value": 1.4, "unit": "kg",
       "source": "카탈로그 2.3 선택사양" }}
  ],
  "cited_evidence_ranks": [1, 2],
  "confidence": 0.0
}}
```

`evidence_blocks` 형식 (근거 하나당):
```
[근거 1] 점수 0.78 (의미 0.74 / 키워드 0.84)
문서: 한빛조명(주) 제품 카탈로그 (HB-CAT-2025-02)
위치: 2. LT-150 사양 > 2.2 구조
모델: LT-150
내용:
| 항목 | 사양 |
|---|---|
| 방수·방진 등급 | IP65 |
| 본체 무게 | 7.2 kg |
...
```

### 3.4 각 절대 규칙이 막는 함정

| 규칙 | 막는 것 |
|---|---|
| 3 (모델 불일치) | **함정 1** — LT-200의 195W·9.8kg를 LT-150 근거로 쓰는 것 |
| 4 (선택사양은 MEET 아님) | **함정 2** 의 전제 — 3.1을 MEET로 처리하면 교차검증 입력이 안 생긴다 |
| 5 (범위 한정 집계) | **함정 3** — 실적 9건을 세어 5.4를 MEET로 판정하는 것 |
| 1, 6 (근거 없으면 CHECK) | **함정 4** — 성적서 없는 시험을 유사 성적서로 MEET 판정하는 것 |
| 2 (지어내기 금지) | 전반적 환각 |

### 3.5 후처리 검증 (`assessor.py`)

LLM 응답을 그대로 저장하지 않는다. 다음을 순서대로 적용한다.

1. `verdict` 가 3값 밖 → `CHECK`, 경고 로그.
2. **`verdict == MEET` 이고 `hits` 가 0건 → `CHECK`, `evidence_state="not_found"`**,
   `rationale` 앞에 `[자동 보정] 근거가 없어 확인 필요로 조정함. ` 을 붙인다. (원칙 3)
3. `verdict == MEET` 이고 `cited_evidence_ranks` 가 비어 있음 → `CHECK`.
4. `evidence_state` 가 `verdict` 와 모순 (예: `MEET` + `not_found`) → `verdict` 를
   `evidence_state` 기준으로 맞춘다 (`not_found`/`found_absent` → `CHECK`).
5. `confidence` 가 없거나 범위 밖 → `None`.
6. `cited_evidence_ranks` 에 해당하는 `hits` 만 `Evidence` 로 저장한다. 인용되지 않은
   검색 결과는 `retrieved_chunk_ids` 에만 남긴다 (화면의 근거 목록이 깨끗해진다).
   단 `verdict != CHECK` 이고 인용이 비면 상위 1건을 저장한다.
7. `ai_verdict = verdict`, `ai_our_value = our_value` 를 저장 시점에 복사한다.

### 3.6 실패 처리

- 개별 요구사항의 LLM 호출이 실패하면 그 항목만 `CHECK` + `rationale="판정 실패: {사유}"`
  로 저장하고 다음 항목으로 넘어간다. 전체 실행을 중단하지 않는다.
- 실패 건수가 전체의 30%를 넘으면 실행을 `failed` 로 종료한다 (LLM 설정 문제일 가능성).
- 진행률은 항목 처리마다 `processed_count` 를 갱신하고 `current_step` 에
  `항목별 판정 (n/total)` 을 쓴다.

---

## 4. 4단계 — 요약 집계

```python
run.summary = {
  "MEET": n, "GAP": n, "CHECK": n,
  "total": 활성 요구사항 수,
  "graded_total": is_graded 인 요구사항 수,
}
```

---

## 5. 5단계 — 교차조항 검증 (`cross_clause.py`)

### 5.1 왜 별도 패스가 필요한가

항목별 독립 판정 구조에서는 조항 간 상충을 **구조적으로 잡을 수 없다.**

조항 3.1(IP66 이상)을 판정할 때 LLM은 3.1과 그 근거만 본다. "IP66 선택사양이 있다"는
사실은 찾지만, 그 선택사양의 무게 증가가 조항 3.2를 위반하는지는 3.2를 모르니 알 수 없다.
3.2를 판정할 때는 표준 무게 7.2kg만 보므로 MEET가 나온다. 둘 다 각각 맞는 판정인데
합치면 **두 조항을 동시에 만족하는 구성이 없다.**

이것은 RAG의 구조적 한계이고, 사람 검토가 필요한 이유다. 그래서 명시적인 후처리 패스를
설계해 최소한 **경고는 띄운다.**

### 5.2 알고리즘

```
입력: 이번 run 의 Assessment 전체
1. side_effects 가 비어 있지 않은 Assessment 를 모은다  → 후보 A
   (주로 GAP 이고 remedy 에 선택사양이 적힌 것)
2. 각 후보 a 에 대해, a.side_effects 의 각 부작용 e:
     e.field 를 다른 요구사항의 category/item 에 매핑한다
       weight      → item 에 "무게" 포함 / category=dimension
       lead_time   → category=delivery / item 에 "납기" 포함
       price       → (요구조건 없음. 정보만 기록)
       temperature → item 에 "온도" 포함
     매핑된 요구사항 b 를 찾는다.
3. b 의 Assessment 에서 our_value 를 수치 파싱한다 (예: "7.2 kg" → 7.2, "kg")
   e 를 적용한다 (op=add → 7.2 + 1.4 = 8.6)
4. b.requirement_text 를 수치 제약으로 파싱한다 ("8 kg 이하" → <= 8.0 kg)
5. 적용 후 값이 제약을 위반하면 CrossClauseIssue 를 생성한다.
   단위가 다르거나 파싱이 실패하면 → LLM 확인 단계(5.3)로 넘긴다.
```

수치 파싱 규칙:
- 값: `([\d,]+(?:\.\d+)?)\s*(W|lm|lm/W|K|kg|mm|시간|℃|%|주|일|년|건|대)`
- 제약: `이하` → `<=`, `이상` → `>=`, `~` 범위 → `[min, max]`, `초과/미만` → `<`, `>`
- 콤마는 제거 후 파싱 (`20,000` → 20000).
- 단위 불일치 시 변환하지 않는다. 경고로 남긴다. (단위 변환 로직은 오류의 원천이다.)

### 5.3 LLM 보조 확인 — `analysis/prompts/cross_clause_check.txt`

수치 파싱으로 판단이 안 되는 조합, 그리고 `GAP` 항목 전체 집합을 LLM에 한 번 보여주고
"동시에 만족할 수 없는 조항 조합이 있는지" 묻는다. 이것은 규칙 기반 검출의 보완이며,
이 단계 없이도 샘플의 3.1 vs 3.2 는 5.2 규칙만으로 검출되어야 한다.

```
아래는 한 입찰 건의 요구조건별 판정 결과다. 대체방안(선택사양)을 적용했을 때 다른
조항을 위반하게 되는 조합, 또는 두 조항을 동시에 만족할 수 없는 조합을 찾는다.

# 규칙
1. 근거에 적힌 수치만 사용한다. 계산 과정을 description 에 남긴다.
2. 확실한 상충만 보고한다. 추측이면 보고하지 않는다.
3. 같은 조항 쌍을 중복 보고하지 않는다.

# 판정 결과
{assessment_blocks}

# 이미 규칙 기반으로 검출된 이슈 (중복 보고 금지)
{known_issues}

# 출력
{{ "issues": [ {{ "clause_nos": ["3.1","3.2"], "kind": "option_side_effect",
   "severity": "high", "title": "", "description": "" }} ] }}
```

### 5.4 샘플 필수 검출 결과

```
clause_nos:  ["3.1", "3.2"]
kind:        option_side_effect
severity:    high
title:       IP66 선택사양 적용 시 조항 3.2 무게 제한 위반
description: 조항 3.1(IP66 이상)은 표준 사양 IP65로 미달하며, IP66 강화 하우징
             선택사양으로 충족할 수 있다. 그러나 이 선택사양은 본체 무게를 1.4kg
             증가시켜 7.2 + 1.4 = 8.6kg 가 되고, 조항 3.2(8 kg 이하)를 위반한다.
             두 조항을 동시에 만족하는 구성이 없으므로 발주처에 우선 적용 기준을
             질의해야 한다.
```

`3.3` 동작온도의 확장 온도 선택사양(단가 +12%, 납기 +2주)은 단가·납기에 대한
수치 제약 조항이 사양서에 없으므로 상충으로 보고하지 않는다. 다만 납기 영향은
공고 `계약체결일로부터 60일 이내` 와 카탈로그 `표준 45일` 을 비교해
`45 + 2주(14일) = 59일 ≤ 60일` 로 여유가 1일임을 `medium` 이슈로 보고할 수 있다.
IP66의 납기 +3주까지 겹치면 `45 + 21 + 14 = 80일 > 60일` 로 `high` 가 된다.
이 계산은 5.2 규칙으로 자연히 나온다.

---

## 6. 6단계 — 취합 (LLM ③)

### 6.1 Compliance Matrix (FR-18)
LLM 호출 없이 `Assessment` 를 표로 직렬화한다. 양식은 `specs/10-output-templates.md` 1절.
공고 5.2("규격 미달 항목은 사유와 대체방안을 대응표에 기재")에 따라 `GAP` 행의
사유·대체방안 열을 `gap_detail` / `remedy` + `side_effects` 로 채운다.

### 6.2 제출서류 체크리스트 (FR-19)
`SubmissionItem` 각 건에 대해 지식베이스를 1회 검색해 보유 상태를 매핑한다
(항목별 1검색 원칙을 여기도 적용한다).

| 서류 | 검색 쿼리 | 기대 결과 |
|---|---|---|
| KS 인증서 사본 | `KS 인증서 KS C 7658` | `have` — 인증현황 `KSC-2022-1180` |
| 고효율에너지기자재 인증서 사본 | `고효율에너지기자재 인증` | `have` — `HE-2023-0471` |
| 납품실적증명서 | `발전소 납품실적` | `uncertain` — 발전 부문 2건뿐 |
| 공인시험기관 시험성적서 | `공인시험기관 시험성적서` | `uncertain` — 4.3/4.4 성적서 없음 |
| 제품 카탈로그 | `제품 카탈로그` | `have` |
| 입찰참가신청서 / 사업자등록증 / 기술규격 대응표 | (검색 불가 항목) | `need` — 자사 자료 대상이 아님 |

마지막 행처럼 지식베이스에 있을 수 없는 서류는 검색하지 말고 `need` 로 고정한다
(발급·작성이 필요한 서류다). 목록은 코드에 상수로 둔다.

### 6.3 기술질의서 초안 (LLM ③) — `analysis/prompts/draft_inquiry.txt`

후보 수집 순서:
1. 모든 `CHECK` 항목 → `source_kind="check"`
2. `remedy` 가 있는 `GAP` 항목 → `source_kind="gap_remedy"`
3. 모든 `CrossClauseIssue` (`is_dismissed=false`) → `source_kind="cross_clause"`

```
발주처에 보낼 기술질의서 문안을 작성한다.

# 규칙
1. 한 질의는 2~3문장. 조항번호를 반드시 앞에 명시한다.
2. 정중한 공문체. "~하여 주시기 바랍니다" 로 끝낸다.
3. 사실만 쓴다. 자사 값은 아래 자료에 적힌 것만 인용한다.
4. 자사에 불리한 표현을 숨기지 않는다. 미달은 미달로 적고 대체방안을 제시한다.
5. 같은 원인의 질의는 하나로 합친다. 조항 3.1과 3.2 상충처럼 두 조항이 걸리면
   clause_refs 에 둘 다 넣고 문안 하나로 쓴다.

# 질의 후보
{candidate_blocks}

# 출력
{{ "inquiries": [ {{ "clause_refs": ["4.3"], "source_kind": "check", "body": "" }} ] }}
```

기대 출력 예 (정답표 6절 기준):
```
조항 4.3 관련: 내염수분무 시험 성적서를 외부 공인기관 위탁으로 대체 제출 가능한지
회신하여 주시기 바랍니다.

조항 3.1 및 3.2 관련: IP66 사양 적용 시 본체 무게가 8kg를 초과합니다.
두 조항 중 우선 적용 기준을 회신하여 주시기 바랍니다.
```

---

## 7. 7단계 — 정확도 측정

`specs/09-acceptance-tests.md` 참조. `evaluator.py` 가 `answer_key.json` 을 읽어
`is_graded=true` 인 요구사항의 `ai_verdict` 와 대조한다.

**측정은 `ai_verdict` 로 한다.** 사람이 수정한 `verdict` 로 측정하면 정확도가 항상
100%가 되어 의미가 없다.

---

## 8. LLM 호출 요약

| 단계 | 프롬프트 | 호출 수 (샘플 기준) |
|---|---|---|
| 요구사항 추출 | `extract_requirements.txt` | 문서당 1 → 2회 |
| 항목별 판정 | `assess_requirement.txt` | 활성 요구사항당 1 → 17회 |
| 교차조항 확인 | `cross_clause_check.txt` | 1회 |
| 제출서류 매핑 | (검색만, LLM 없음) | 0회 |
| 기술질의서 초안 | `draft_inquiry.txt` | 1회 |
| **합계** | | **약 21회** + 임베딩 (쿼리당 1) |

`temperature=0` 고정. 전체 실행 시간 목표: 2분 이내.

## 9. 테스트 시 LLM 대체

`settings.LLM_FAKE=True` 면 `common/llm.py` 가 실제 호출 대신 고정 응답을 반환한다.
응답 픽스처는 `backend/analysis/fixtures/llm_responses/` 에 프롬프트 이름 + 입력 해시로 둔다.
이렇게 하면 파이프라인 오케스트레이션·검증·집계 로직을 API 키 없이 테스트할 수 있다.
프롬프트 품질(= 정확도)은 실제 호출로만 측정한다.
