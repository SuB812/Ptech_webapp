# 04. REST API 명세

Base URL: `/api`. 모든 요청·응답은 `application/json` (업로드만 `multipart/form-data`).
인증 없음 (PoC). 필드명은 영어 snake_case, 사용자에게 보이는 문자열만 한국어.

이 문서가 프론트-백엔드 계약의 **단일 기준**이다. 필드를 추가하면 여기를 먼저 고친다.

## 0. 공통

### 에러 형태

```json
{ "detail": "PDF 파일만 업로드할 수 있습니다.", "code": "invalid_file_type" }
```

| 코드 | HTTP | 의미 |
|---|---|---|
| `invalid_file_type` | 400 | 허용되지 않는 확장자 |
| `file_too_large` | 400 | 20MB 초과 |
| `too_many_pages` | 400 | 50페이지 초과 |
| `knowledge_doc_type_forbidden` | 400 | 공고문·사양서를 지식베이스에 업로드 시도 |
| `extraction_failed` | 422 | PDF 텍스트 레이어 없음 등 |
| `llm_unavailable` | 503 | `OPENAI_API_KEY` 미설정 또는 LLM 호출 실패 |
| `meet_without_evidence` | 400 | 근거 없이 `MEET` 저장 시도 (원칙 3) |
| `run_in_progress` | 409 | 같은 입찰 건에 실행 중인 분석이 있음 |

### 페이지네이션
목록 응답은 DRF 기본 형태 `{count, next, previous, results}`. `page_size=50`.

---

## 1. 입찰 건 (FR-22)

### `GET /api/projects/`
```json
{ "count": 1, "results": [
  { "id": 1, "title": "○○화력발전소 구내 LED 투광등 교체",
    "bid_no": "KPG-2025-EQ-0417", "org": "한국발전기술공사 자재구매처",
    "bid_due_at": "2025-07-24T10:00:00+09:00",
    "document_count": 2, "requirement_count": 17,
    "latest_run": { "id": 5, "status": "done", "finished_at": "...",
                    "summary": {"MEET":7,"GAP":4,"CHECK":2,"total":13},
                    "accuracy": {"score":11,"total":13} } } ] }
```

### `POST /api/projects/`
요청: `{ "title": "..." }` (나머지는 FR-05 추출로 채워짐). → `201` + 상세.

### `GET /api/projects/{id}/`
상세. `BidProject` 전체 필드 + `documents[]` + `participation_reqs[]` + `submission_items[]` + `runs[]` 요약.

### `DELETE /api/projects/{id}/`
`204`. 연관 문서·요구사항·실행 결과를 함께 삭제한다. 업로드 파일도 삭제한다.

---

## 2. 입력 문서 (FR-01, FR-02, FR-05)

### `POST /api/projects/{id}/documents/`
`multipart/form-data`: `file` (필수, `.pdf`), `doc_type` (`announcement` | `techspec`).

업로드 → 동기적으로 텍스트·표 추출 → `201`:
```json
{ "id": 3, "doc_type": "techspec", "original_name": "02_기술사양서.pdf",
  "doc_no": "KPG-2025-TS-0417", "page_count": 1, "status": "parsed",
  "table_count": 4, "error_message": "" }
```
추출 실패 시에도 레코드는 생성하고 `status="failed"`, `error_message` 를 채워 `201` 을 반환한다
(사용자가 화면에서 사유를 보고 다시 올릴 수 있게).

### `GET /api/documents/{id}/pages/`
추출 원문 확인용.
```json
[ { "page_no": 1, "text": "1.1 본 사양서는 ...", "tables": [
      { "index": 0, "rows": [["조항","항목","요구조건"],["2.1","소비전력","150 W 이하"]] } ] } ]
```

### `DELETE /api/documents/{id}/` → `204`

### `POST /api/projects/{id}/extract/` (FR-03, FR-04, FR-05)
업로드된 문서 전체에서 요구사항·제출서류·참가자격·기본정보를 추출한다. LLM을 호출한다.

요청: `{ "replace": true }` — `true` 면 기존 추출 결과를 지우고 다시 만든다.
사용자가 수정한 요구사항이 있으면 `replace=true` 에 경고를 프론트에서 먼저 띄운다.

응답 `200`:
```json
{ "requirement_count": 17, "submission_count": 8, "participation_count": 3,
  "project": { "...": "FR-05로 채워진 헤더 정보" },
  "warnings": ["조항 4.4의 기준 열이 비어 있습니다. 확인이 필요합니다."] }
```

---

## 3. 요구사항 (FR-07)

### `GET /api/projects/{id}/requirements/`
쿼리: `?category=`, `?is_active=`, `?is_graded=`. 기본 정렬 `order`.
```json
[ { "id": 11, "clause_no": "2.1", "chapter": "제2장 성능 요구사항",
    "category": "efficiency", "category_label": "효율",
    "item": "소비전력", "requirement_text": "150 W 이하",
    "context_text": "", "source_page": 1, "order": 1,
    "is_active": true, "is_graded": true, "is_edited": false } ]
```

### `PATCH /api/requirements/{id}/`
수정 가능 필드: `clause_no`, `item`, `requirement_text`, `category`, `is_active`, `is_graded`.
수정 시 서버가 `is_edited=true` 로 설정하고 `ai_*` 필드는 건드리지 않는다.

### `POST /api/projects/{id}/requirements/`
행 수동 추가. `order` 미지정 시 맨 뒤.

### `DELETE /api/requirements/{id}/`
`204`. 다만 프론트 기본 동작은 `PATCH is_active=false` 다 (추출 원본 보존).

---

## 4. 지식베이스 (FR-08, FR-09, FR-12)

### `GET /api/knowledge/documents/`
```json
[ { "id": 1, "title": "한빛조명(주) 제품 카탈로그", "doc_no": "HB-CAT-2025-02",
    "doc_kind": "catalog", "doc_kind_label": "제품카탈로그",
    "revision_date": "2025-05-10", "status": "indexed",
    "chunk_count": 34, "embedding_model": "text-embedding-3-small" } ]
```

### `POST /api/knowledge/documents/`
`multipart/form-data`: `file` (`.pdf` | `.md`), `doc_kind`, `title`(옵션 — 없으면 문서 첫 제목),
`doc_no`(옵션 — 없으면 `문서번호:` 줄에서 추출).

색인은 백그라운드 스레드. 즉시 `201` + `status="indexing"`. 프론트가 폴링한다.

**서버 검증**: 파일명이나 내용에서 입찰공고문·기술사양서로 판단되면 `400 knowledge_doc_type_forbidden`.
판단 규칙 — 파일명에 `공고`/`사양서`/`RFP`/`규격서` 포함, 또는 본문에 `공고번호` 패턴 존재.
오탐 가능성이 있으므로 에러 메시지에 "자사 자료가 맞다면 파일명을 바꿔 다시 올려주세요"를 넣는다.

### `POST /api/knowledge/documents/{id}/reindex/`
기존 청크를 삭제하고 다시 청킹·임베딩. `202` + `status="indexing"`.

### `DELETE /api/knowledge/documents/{id}/`
`204`. 청크도 삭제. 과거 `Evidence` 는 스냅샷 필드 덕분에 표시가 유지된다.

### `GET /api/knowledge/documents/{id}/chunks/`
청킹 결과 확인용. 쿼리 `?is_parent=false`.
```json
[ { "id": 120, "is_parent": false, "parent": 118, "chunk_type": "table_row",
    "section_path": "2.2 구조 > 방수·방진 등급", "content": "방수·방진 등급: IP65",
    "keywords": ["IP65"], "model_tags": ["LT-150"], "token_count": 12 } ]
```

### `POST /api/knowledge/search/` (FR-12 검색 테스트)
요청:
```json
{ "query": "염수분무 시험", "top_k": 5, "threshold": 0.4,
  "w_semantic": 0.6, "w_keyword": 0.4, "model_filter": "LT-150" }
```
응답:
```json
{ "query": "염수분무 시험", "params": {"...": "적용된 값"},
  "results": [
    { "chunk_id": 205, "score": 0.71, "semantic_score": 0.63, "keyword_score": 0.83,
      "doc_title": "한빛조명(주) 인증·시험·실적 현황", "doc_no": "HB-QA-2025-07",
      "location": "3. 시험 설비 보유 현황", "page_no": null,
      "content": "염수분무 시험기: 미보유",
      "parent_content": "| 설비명 | 보유 여부 |\n|---|---|\n| 적분구 ... |",
      "model_tags": [], "rank": 1 } ] }
```

---

## 5. 분석 실행 (FR-11, FR-13, FR-16)

### `POST /api/projects/{id}/runs/`
요청 (전부 옵션, 미지정 시 `.env` 기본값):
```json
{ "top_k": 5, "threshold": 0.4, "w_semantic": 0.6, "w_keyword": 0.4,
  "llm_model": "gpt-4o", "enable_cross_clause": true }
```
`202`:
```json
{ "id": 5, "status": "queued", "total_count": 17, "processed_count": 0 }
```
같은 입찰 건에 `queued`/`running` 실행이 있으면 `409 run_in_progress`.
활성 요구사항이 0건이면 `400`.

### `GET /api/runs/{id}/` (폴링 대상, 2초 간격)
```json
{ "id": 5, "project": 1, "status": "running",
  "current_step": "항목별 판정 (7/17)", "total_count": 17, "processed_count": 7,
  "llm_model": "gpt-4o", "embedding_model": "text-embedding-3-small",
  "rag_params": {"top_k":5,"threshold":0.4,"w_semantic":0.6,"w_keyword":0.4},
  "prompt_versions": {"extract_requirements":"sha1:...","assess_requirement":"sha1:..."},
  "started_at": "...", "finished_at": null, "error_message": "",
  "summary": null, "accuracy": null,
  "token_usage": {"prompt":18400,"completion":5200},
  "elapsed_ms": 41200 }
```
`status="done"` 이 되면 폴링을 멈추고 결과를 가져온다.

### `GET /api/projects/{id}/runs/` — 실행 이력 목록 (FR-23)

### `GET /api/runs/{id}/assessments/`
쿼리: `?verdict=MEET|GAP|CHECK`, `?category=`, `?is_edited=`.
```json
[ { "id": 88, "requirement": {
      "id": 21, "clause_no": "3.1", "chapter": "제3장 구조 요구사항",
      "category": "filter_grade", "category_label": "등급",
      "item": "방수·방진 등급", "requirement_text": "IP66 이상" },
    "verdict": "GAP", "verdict_label": "보완 필요", "ai_verdict": "GAP",
    "evidence_state": "found_insufficient",
    "our_value": "IP65", "ai_our_value": "IP65",
    "rationale": "카탈로그 2.2에 표준 방수 등급이 IP65로 명시되어 요구 IP66에 한 등급 미달한다.",
    "gap_detail": "한 등급 미달 (IP65 < IP66)",
    "remedy": "IP66 강화 하우징 선택사양 적용 가능",
    "remedy_side_effects": [
      {"field":"weight","op":"add","value":1.4,"unit":"kg","source":"카탈로그 2.3"},
      {"field":"lead_time","op":"add","value":3,"unit":"주","source":"카탈로그 2.3"} ],
    "confidence": 0.92,
    "retrieval_query": "방수·방진 등급 IP66 이상 LT-150",
    "is_edited": false, "edited_at": null,
    "evidences": [
      { "id": 301, "chunk": 120, "doc_title": "한빛조명(주) 제품 카탈로그",
        "doc_no": "HB-CAT-2025-02", "location": "2.2 구조", "page_no": null,
        "quote": "방수·방진 등급: IP65", "score": 0.78,
        "semantic_score": 0.74, "keyword_score": 0.84, "rank": 1 } ] } ]
```

### `GET /api/assessments/{id}/evidences/{eid}/`
근거 모달용. `parent_content` 전문을 포함해 반환한다.

### `PATCH /api/assessments/{id}/` (FR-17)
수정 가능: `verdict`, `our_value`, `rationale`, `gap_detail`, `remedy`.
서버가 `is_edited=true`, `edited_at=now` 를 설정한다. `ai_*` 는 불변.
`verdict="MEET"` 인데 근거가 0건이면 `400 meet_without_evidence`.

### `GET /api/runs/{id}/cross-issues/` (FR-16)
```json
[ { "id": 4, "clause_nos": ["3.1","3.2"], "kind": "option_side_effect",
    "severity": "high",
    "title": "IP66 선택사양 적용 시 조항 3.2 무게 제한 위반",
    "description": "조항 3.1(IP66 이상)을 IP66 강화 하우징 선택사양으로 충족하면 본체 무게가 7.2kg + 1.4kg = 8.6kg가 되어 조항 3.2(8kg 이하)를 위반한다. 두 조항을 동시에 만족하는 구성이 없다.",
    "requirements": [21, 22], "is_dismissed": false } ]
```

### `PATCH /api/cross-issues/{id}/` — `{"is_dismissed": true}`

---

## 6. 산출물 (FR-18 ~ FR-21)

### `POST /api/runs/{id}/deliverables/`
요청: `{ "kinds": ["matrix","checklist","inquiry"] }`. LLM로 기술질의서 문안을 생성한다. `200`:
```json
{ "matrix": { "rows": [ { "clause_no":"3.1", "category_label":"등급", "item":"방수·방진 등급",
      "requirement_text":"IP66 이상", "our_value":"IP65", "verdict_label":"보완 필요",
      "reason":"한 등급 미달", "remedy":"IP66 강화 하우징 선택사양 적용 (무게 +1.4kg, 납기 +3주)",
      "evidence":"카탈로그 2.2 구조" } ] },
  "checklist": { "documents": [ { "seq":1, "name":"입찰참가신청서", "note":"소정양식",
        "status":"need", "status_label":"발급 필요", "evidence_text":"" } ],
      "participation": [ { "seq":"3.3", "text":"최근 5년 이내 발전소 납품실적이 3건 이상인 자",
        "status":"uncertain", "status_label":"확인 필요",
        "note":"발전 부문 실적 2건 (남부발전 2022, 서부발전 2024)" } ],
      "schedule": { "inquiry_due_at":"2025-07-10", "bid_due_at":"2025-07-24T10:00:00+09:00" } },
  "inquiry": { "items": [ { "id":9, "seq":1, "clause_refs":["4.3"], "source_kind":"check",
        "body":"조항 4.3 관련: 내염수분무 시험 성적서를 외부 공인기관 위탁으로 대체 제출 가능한지 회신하여 주시기 바랍니다.",
        "is_included":true, "is_edited":false } ] } }
```

### `GET /api/runs/{id}/deliverables/` — 생성된 산출물 재조회 (LLM 재호출 없음)

### `PATCH /api/inquiries/{id}/` — `{"body": "...", "is_included": false}`

### `POST /api/runs/{id}/export/`
요청: `{ "kind": "xlsx" }` 또는 `{ "kind": "markdown" }`. `201`:
```json
{ "id": 2, "kind": "xlsx",
  "filename": "KPG-2025-EQ-0417_대응자료_20250928.xlsx",
  "download_url": "/api/exports/2/download/", "size_bytes": 24810 }
```

### `GET /api/exports/{id}/download/`
바이너리 응답. `Content-Disposition: attachment; filename*=UTF-8''...`
(한글 파일명이므로 RFC 5987 인코딩을 쓴다.)

---

## 7. 정확도 측정 (FR-24)

### `POST /api/runs/{id}/evaluate/`
`backend/analysis/fixtures/answer_key.json` 과 대조한다.
```json
{ "score": 11, "total": 13, "accuracy": 0.846,
  "by_verdict": {
    "MEET":  {"expected":7,"correct":6},
    "GAP":   {"expected":4,"correct":3},
    "CHECK": {"expected":2,"correct":2} },
  "confusion": [ {"expected":"GAP","actual":"MEET","count":1} ],
  "mismatches": [
    { "clause_no":"5.4", "item":"납품실적", "expected":"GAP", "actual":"MEET",
      "ai_our_value":"9건", "ai_rationale":"납품실적 총 9건 보유",
      "note":"함정 3 — 발전 부문만 집계해야 함 (2건)" } ],
  "traps": [
    { "id":"TRAP-1", "name":"모델 혼동",           "passed":true,  "detail":"..." },
    { "id":"TRAP-2", "name":"선택사양 연쇄 효과",   "passed":true,  "detail":"..." },
    { "id":"TRAP-3", "name":"실적 분류",           "passed":false, "detail":"..." },
    { "id":"TRAP-4", "name":"시험 부재 확인",       "passed":true,  "detail":"..." } ] }
```
결과는 `AnalysisRun.accuracy` 에 저장한다. `GET /api/runs/{id}/` 로 다시 읽을 수 있다.

### `GET /api/answer-key/`
정답표를 읽기 전용으로 반환한다 (화면에서 정답과 나란히 비교하기 위함).
`Assessment` 생성 코드는 이 엔드포인트나 픽스처를 **참조하지 않는다.**

---

## 8. 엔드포인트 요약

| 메서드 | 경로 | FR |
|---|---|---|
| GET POST | `/api/projects/` | FR-22 |
| GET DELETE | `/api/projects/{id}/` | FR-22 |
| POST | `/api/projects/{id}/documents/` | FR-01, 02 |
| GET | `/api/documents/{id}/pages/` | FR-02 |
| DELETE | `/api/documents/{id}/` | FR-01 |
| POST | `/api/projects/{id}/extract/` | FR-03, 04, 05 |
| GET POST | `/api/projects/{id}/requirements/` | FR-06, 07 |
| PATCH DELETE | `/api/requirements/{id}/` | FR-07 |
| GET POST | `/api/knowledge/documents/` | FR-08 |
| POST | `/api/knowledge/documents/{id}/reindex/` | FR-08 |
| DELETE | `/api/knowledge/documents/{id}/` | FR-08 |
| GET | `/api/knowledge/documents/{id}/chunks/` | FR-09 |
| POST | `/api/knowledge/search/` | FR-10, 12 |
| POST | `/api/projects/{id}/runs/` | FR-11, 13 |
| GET | `/api/projects/{id}/runs/` | FR-23 |
| GET | `/api/runs/{id}/` | FR-23 |
| GET | `/api/runs/{id}/assessments/` | FR-15 |
| PATCH | `/api/assessments/{id}/` | FR-17 |
| GET | `/api/assessments/{id}/evidences/{eid}/` | FR-14 |
| GET | `/api/runs/{id}/cross-issues/` | FR-16 |
| PATCH | `/api/cross-issues/{id}/` | FR-16 |
| GET POST | `/api/runs/{id}/deliverables/` | FR-18, 19, 20 |
| PATCH | `/api/inquiries/{id}/` | FR-20 |
| POST | `/api/runs/{id}/export/` | FR-21 |
| GET | `/api/exports/{id}/download/` | FR-21 |
| POST | `/api/runs/{id}/evaluate/` | FR-24 |
| GET | `/api/answer-key/` | FR-24 |
