# 12. 개발 계획 (13 Phase)

`specs/00`~`11` 을 구현 순서로 옮긴 문서. Phase 를 건너뛰지 않는다.
각 Phase 완료 시점에 `specs/09-acceptance-tests.md` 의 어떤 항목을 검증할 수 있는지 명시한다.

---

## 0. Phase 순서의 근거

1. **PDF 파서를 1번으로 둔다.** 표 추출이 틀리면 그 뒤 모든 판정이 오답이 된다
   (`05-rag-pipeline.md` 2.1 의 `pdftotext` 열 밀림). 그리고 파서는 Django·DB·API 키가
   전부 필요 없는 순수 함수라 지금 당장 실측으로 검증할 수 있다.
2. **RAG 를 UI 보다 앞에 둔다.** 청킹이 잘못되면 `염수분무 시험기: 미보유` 가 검색되지 않고
   TRAP-4 는 원리적으로 통과 불가다. 화면을 만들기 전에 검색이 되는지부터 확인한다.
3. **P7 에서 처음으로 `n/13` 숫자가 나온다.** 이것이 PoC 의 실질적 완료 지점이고,
   P8~P11 은 그 결과를 사람이 보고 고칠 수 있게 만드는 작업이다.

---

## 1. 환경 실측 결과 (2026-09-28, 개발 PC 기준)

| 항목 | 상태 |
|---|---|
| Python | 3.12.0 — 요구 3.11+ 충족 |
| Node / npm | 24.20.0 / 11.19.0 — 요구 20+ 충족 |
| PostgreSQL | 16.15 설치·실행 중, 5432 LISTEN |
| pgvector | **0.8.6 설치 완료** (`lib/vector.dll` + `share/extension/vector.control`) |
| pg_trgm | 기본 포함, 사용 가능 |
| `psql` | PATH 에 없음 → `C:\Program Files\PostgreSQL\16\bin\psql.exe` 전체 경로 사용 |
| `ptech` DB / role | 미생성 → `backend/db_init.sql` 로 생성 (Phase 0-B) |

`11-dev-setup.md` 2.1 이 경고하는 pgvector 수동 설치는 이 PC 에서 이미 완료되었다.
가장 큰 설치 리스크가 없다.

---

## 2. API 키 경계

| 구간 | 키 | 비고 |
|---|---|---|
| P0 ~ P3 | **불필요** | 파서·모델·청킹은 LLM 무관. 키워드는 정규식 |
| P4 실제 색인 | **필요** ← 키가 처음 필요한 지점 | `text-embedding-3-small` |
| P4 검색 로직 테스트 | 불필요 (`LLM_FAKE`) | 결정적 의사 임베딩 (`02-architecture.md` 5절) |
| P5, P6 | 필요 | LLM ①②. 검증·집계 로직은 `LLM_FAKE` 로 테스트 |
| P7 교차조항 규칙 + evaluator | **불필요** | 순수 수치 파싱 + 픽스처 대조 |
| P7 LLM 보조 확인 | 필요 (선택) | 규칙만으로 TRAP-2 는 통과해야 한다 |
| P8 대응표·체크리스트·Excel | 불필요 | |
| P8 기술질의서 문안 | 필요 | LLM ③ |
| P9 ~ P11 프론트 | 불필요 | 백엔드 응답만 있으면 된다 |
| P12 튜닝 루프 | 필요 | 반복 측정 |

`pytest` 기본 실행은 `addopts = -m "not llm"` + `LLM_FAKE=True` 라 **키 없이 돈다**
(`11-dev-setup.md` 7절).

---

## Phase 0 — 환경 및 프로젝트 골격

0-A(차단 없음)와 0-B(postgres 슈퍼유저 비밀번호 필요)로 나뉜다.

**1. 목표** — `pytest` 와 `manage.py check` 가 도는 빈 프로젝트.

**2. 구현할 기능** — 없음 (인프라).

**3. 생성할 파일**
```
backend/requirements.txt  pytest.ini  manage.py  db_init.sql
backend/config/{__init__,settings,urls,wsgi,asgi}.py
backend/common/{__init__,enums,llm}.py
backend/{projects,documents,knowledge,analysis,exports}/   # startapp x5
.env                                                       # 커밋 금지
```

**4. 수정할 파일** — 없음.

**5. 사용할 명령**
```powershell
# 0-A
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
django-admin startproject config .
python manage.py startapp projects   # documents knowledge analysis exports 반복

# 0-B (사용자가 직접 — 비밀번호 입력 필요)
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U postgres -h localhost -f backend\db_init.sql
```

**6. 테스트 및 검증**
- `python manage.py check` — DB 접속 없이 통과해야 한다
- `pytest` — 0 테스트 수집 성공 (설정 오류 없음)
- 0-B 후: `SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm');`
- 0-B 후: `python manage.py migrate` (Phase 2 에서 실제 마이그레이션 생성)

**7. 완료 조건**
- `manage.py check` 무오류
- `.env` 가 `git status` 에 나타나지 않음
- 0-B: `ptech` DB 에서 `vector`·`pg_trgm` 확장 확인

**09 검증 항목** — 없음.

---

## Phase 1 — 문서 파서 ★ 최우선

**1. 목표** — 샘플 PDF 2건·MD 2건에서 표를 한 칸도 어긋나지 않게 뽑는다.

**2. 구현할 기능** — FR-02 (추출 엔진), `05-rag-pipeline.md` 2.2 추출 절차,
2.3 검증·경고, 2.4 Markdown 파싱.

**3. 생성할 파일**
```
backend/common/tables.py                      # 2차원 배열 → Markdown 표 직렬화 (LLM 입력용)
backend/documents/services/__init__.py
backend/documents/services/pdf_extract.py     # pdfplumber 텍스트/표 추출 + 검증 경고
backend/knowledge/services/__init__.py
backend/knowledge/services/md_parse.py        # 헤딩 트리 + GFM 표 + 문서번호/개정일
backend/documents/tests/test_pdf_extract.py
backend/knowledge/tests/test_md_parse.py
```

**4. 수정할 파일** — `backend/requirements.txt` (pdfplumber·pypdf 버전 확정 시).

**5. 사용할 명령**
```powershell
pytest documents/tests/test_pdf_extract.py knowledge/tests/test_md_parse.py -v
```

**6. 테스트 및 검증** — `08-sample-data.md` 값과 **셀 단위로** 단정한다.
- 사양서 표 4개. `['2.1','소비전력','150 W 이하']` — `150 W 이하` 가 `2.2` 행에 붙으면 실패
- 공고문 표 3개. 제출서류 8행, `8 / 공인시험기관 시험성적서 / 기술사양서 제4장 전체`
- `4.4 내진동 시험` 기준 열 경고가 `warnings` 에 올라오고 **자동 수정되지 않음**
- 표 밖 서술 보존: `해안에서 약 2km`, `미달 시 대체방안을 대응표에 명시`
- 스캔 PDF 가드: 텍스트 50자 미만 → `extraction_failed`
- MD: `HB-CAT-2025-02` / `2025-05-10`, `HB-QA-2025-07` / `2025-06-30` 추출

**7. 완료 조건** — 위 단정 전부 통과. DB·API 키 없이 `pytest` 통과.

**09 검증 항목** — `test_pdf_extract_tables`, `test_pdf_extract_announcement` (§7.1).

---

## Phase 2 — 데이터 모델

**1. 목표** — `03-data-model.md` 전체를 마이그레이션까지 반영.

**2. 구현할 기능** — FR-06 (분류 enum), FR-22 (목록/생성 스모크).

**3. 생성할 파일**
```
projects/models.py      # BidProject, ParticipationRequirement, SubmissionItem
documents/models.py     # SourceDocument, DocumentPage, Requirement
knowledge/models.py     # KnowledgeDocument, KnowledgeChunk
analysis/models.py      # AnalysisRun, Assessment, Evidence, CrossClauseIssue,
                        # InquiryDraft, ExportFile
common/sorting.py       # 조항번호 숫자 튜플 정렬
projects/{serializers,views,urls}.py          # 최소 ViewSet
*/migrations/0001_*.py  # VectorExtension + TrigramExtension 포함
*/tests/test_models.py
```

**4. 수정할 파일** — `config/settings.py` (앱 등록), `config/urls.py`.

**5. 사용할 명령**
```powershell
python manage.py makemigrations
python manage.py migrate
pytest -k "model or sorting" -v
```

**6. 테스트 및 검증**
- `VectorExtension` + `TrigramExtension` 적용
- HNSW / GIN 인덱스 4개 생성 확인 (`03-data-model.md` 4절 SQL)
- `unique_together` 위반 테스트 (`Requirement`, `Assessment`)
- `SourceDocument` 에 `KnowledgeChunk` FK 가 **존재하지 않음**을 코드로 단정

**7. 완료 조건** — `GET /api/projects/` 가 `{"count":0,...}` 반환.

**09 검증 항목** — `test_clause_no_sorting`, `test_source_doc_never_indexed` 의 구조 부분.

---

## Phase 3 — 부모-자식 청킹 · 키워드 · model_tags

**1. 목표** — 자사 자료 2건을 검색 가능한 청크로 쪼갠다. **TRAP-1·3·4 의 전제가 여기서 결정된다.**

**2. 구현할 기능** — FR-09.

**3. 생성할 파일**
```
knowledge/services/chunker.py     # 부모-자식, 표 행 자연어화, section_path, model_tags
knowledge/services/keywords.py    # 정규식 7패턴 (05 3.4절)
knowledge/tests/test_chunker.py
knowledge/tests/test_keywords.py
```

**4. 수정할 파일** — 없음.

**5. 사용할 명령** — `pytest knowledge/tests -v`

**6. 테스트 및 검증**
- 표 1개 = 부모 1개, 표 행 수 = 자식 수
- 청크 수가 `05-rag-pipeline.md` 3.6 범위 내 (카탈로그 부모 10~14·자식 35~50,
  QA 부모 12~16·자식 45~65)
- 아래 3개 청크가 반드시 존재한다

| 청크 | 방어하는 함정 |
|---|---|
| `염수분무 시험기: 미보유`, `진동 시험기: 미보유` (행 단위 자식) | TRAP-4 |
| LT-200 절 하위 청크의 `model_tags == ["LT-200"]` | TRAP-1 |
| `section_path` 에 `4.1 발전 부문` 포함 | TRAP-3 |

**7. 완료 조건** — 위 3개 청크 존재 + 청크 수 범위 내.

**09 검증 항목** — `test_chunker_parent_child`, `test_chunker_model_tags`,
`test_chunker_equipment_table`, `test_keyword_extraction` (§7.1).

> 이 Phase 가 부실하면 P6·P7 에서 프롬프트를 아무리 고쳐도 함정을 통과할 수 없다.
> 청크를 눈으로 확인하고 넘어간다.

---

## Phase 4 — 임베딩 · 하이브리드 검색 · 지식베이스 API

**1. 목표** — `IP66` 쿼리가 `IP65` 청크보다 `IP66` 청크를 위로 올린다.

**2. 구현할 기능** — FR-08, FR-10, FR-12 (API).

**3. 생성할 파일**
```
knowledge/services/embedder.py    # 자식 청크만, 배치 64, 3회 백오프
knowledge/services/retriever.py   # pgvector + pg_trgm 가중합, 모델 필터 재랭크
knowledge/{serializers,views,urls}.py
knowledge/management/commands/load_knowledge.py
knowledge/tests/test_retriever.py
knowledge/tests/test_knowledge_api.py
```

**4. 수정할 파일** — `common/llm.py` (임베딩 + `LLM_FAKE` 의사 임베딩),
`config/urls.py`, `.env.example` (변경 시).

**5. 사용할 명령**
```powershell
python manage.py load_knowledge ../samples/03_자사_제품카탈로그.md --kind catalog
python manage.py load_knowledge ../samples/04_자사_인증_시험_실적.md --kind qa
pytest knowledge/tests -v
python manage.py shell -c "from knowledge.models import KnowledgeChunk as C; print(C.objects.count())"
```

**6. 테스트 및 검증** — `POST /api/knowledge/search/` 로 `05-rag-pipeline.md` 6절
기준 쿼리 3개를 수동 확인한다.

| 쿼리 | 기대 | 실패 시 |
|---|---|---|
| `방수 등급` | IP65 표준 + IP66 선택사양 + HB-T-2024-012 | 청킹 재검토 |
| `발전소 납품실적` | 4.1 발전 부문 표 상위 | TRAP-3 위험 |
| **`염수분무 시험`** | **`염수분무 시험기: 미보유` 상위** | **TRAP-4 통과 불가 → P3 복귀** |

**7. 완료 조건** — 기준 쿼리 3개 전부 통과 + 공고문 업로드가 400 으로 거부됨.

**09 검증 항목** — `test_retriever_keyword_exact`, `test_retriever_model_filter`,
`test_knowledge_rejects_bid_doc` (§7.1).

---

## Phase 5 — 입력 문서 API · 요구사항 추출 (LLM ①)

**1. 목표** — 사양서에서 17개 조항이 값 왜곡 없이 나온다.

**2. 구현할 기능** — FR-01, 02(API), 03, 04, 05, 07(API), 22.

**3. 생성할 파일**
```
documents/services/requirement_extract.py
analysis/prompts/extract_requirements.txt
documents/{serializers,views,urls}.py
projects/management/commands/load_sample_bid.py
analysis/fixtures/llm_responses/            # LLM_FAKE 픽스처
documents/tests/test_extract.py
```

**4. 수정할 파일** — `projects/views.py` (extract 액션),
`common/llm.py` (chat + JSON 스키마 검증 + 1회 재시도).

**5. 사용할 명령**
```powershell
python manage.py load_sample_bid
pytest -k extract -v            # LLM_FAKE
pytest -m llm -k extract -v     # 실제 키 필요
```

**6. 테스트 및 검증**
- 17개 조항 + 공고 참가자격 3건
- `150 W 이하` 원문 표기 유지 (`150W` 로 줄이지 않음)
- `1.2 해안 2km` 가 `3.1`·`4.3` 의 `context_text` 로 들어감
- `5.3 문의 전화번호` 미추출 (프롬프트 규칙 7)
- `warnings` 전량 반환

**7. 완료 조건** — `POST /projects/{id}/extract/` 가 `requirement_count: 17`,
`submission_count: 8`, `participation_count: 3`.

**09 검증 항목** — `test_extract_17_clauses` (§7.2),
`test_source_doc_never_indexed` 완전 검증, §6 "요구사항 추출 17개 조항 전부".

---

## Phase 6 — 항목별 검색·판정 파이프라인 (LLM ②)

**1. 목표** — 항목 하나당 검색 한 번으로 판정하고, 근거 없는 `MEET` 을 구조적으로 못 만들게 한다.

**2. 구현할 기능** — FR-11, 13, 14, 17.

**3. 생성할 파일**
```
analysis/services/pipeline.py     # 스레드 오케스트레이션, 진행률
analysis/services/assessor.py     # 06 3.5절 후처리 검증 7단계
analysis/prompts/assess_requirement.txt
analysis/{serializers,views,urls}.py
analysis/tests/test_assessor.py
analysis/tests/test_pipeline.py
```

**4. 수정할 파일** — `config/settings.py` (기동 시 `running` → `failed` 정리).

**5. 사용할 명령**
```powershell
pytest analysis/tests -v
# POST /api/projects/1/runs/  후  GET /api/runs/1/ 폴링
```

**6. 테스트 및 검증**
- 요구사항 N건 → 검색 호출 **정확히 N회** (묶음 검색 0회) 를 mock 카운트로 단정
- `MEET` + 근거 0건 → `CHECK` 강제 + `[자동 보정]` 프리픽스
- `PATCH /assessments/{id}/` 로 `MEET` 시도 시 `400 meet_without_evidence`
- 개별 항목 실패가 전체를 죽이지 않음 (30% 룰)
- `retrieval_query`·`retrieved_chunk_ids` 저장 (재현성)

**7. 완료 조건** — 전 항목 판정 완료, **근거 없는 `MEET` 0건**.

**09 검증 항목** — `test_meet_without_evidence_rejected`,
`test_meet_without_evidence_api` (§7.1) · TRAP-1·3·4 1차 측정 가능 ·
§6 "근거 없는 MEET 0건" (위반 시 무조건 불합격).

---

## Phase 7 — 교차조항 검증 · 정확도 측정 ★ 핵심 마일스톤

**1. 목표** — `n/13` 숫자와 함정 4개 O/X 가 처음 나온다.

**2. 구현할 기능** — FR-16, FR-24.

**3. 생성할 파일**
```
analysis/services/cross_clause.py   # 수치 파싱 + 제약 비교 (06 5.2절)
analysis/services/evaluator.py      # answer_key.json 대조
analysis/prompts/cross_clause_check.txt
analysis/fixtures/answer_key.json   # 09 4절 형식
analysis/management/commands/evaluate_run.py
analysis/management/commands/mark_graded.py   # is_graded 지정 (03 6절 예외)
analysis/tests/test_cross_clause.py
analysis/tests/test_evaluator.py
```

**4. 수정할 파일** — `analysis/services/pipeline.py` (5단계 삽입),
`analysis/views.py` (evaluate, cross-issues, answer-key).

**5. 사용할 명령**
```powershell
pytest analysis/tests/test_cross_clause.py analysis/tests/test_evaluator.py -v
python manage.py mark_graded --project 1
python manage.py evaluate_run --run-id 1
```

**6. 테스트 및 검증** — 규칙 기반만으로 (LLM 없이) 아래 2건이 검출되어야 한다.
```
3.1 + 3.2  →  7.2 + 1.4 = 8.6kg > 8kg     severity = high     (TRAP-2)
납기        →  45 + 21 = 66일 > 60일        severity ≥ medium
```
채점은 `ai_verdict` 로만 한다. `expected_verdict` 일치만 13점 만점이며
`our_value` 표기 차이는 감점하지 않고 함정 판정·오답 분석에만 쓴다.

**7. 완료 조건** — 정확도 ≥ 10/13, TRAP-1·3·4 통과 (§6 최소 기준).

**09 검증 항목** — `test_cross_clause_weight_conflict`, `test_cross_clause_lead_time`,
`test_evaluator_scoring` (§7.1) · `test_full_pipeline_accuracy`, `test_traps` (§7.2) ·
**§6 합격 기준 전체를 처음으로 측정**.

---

## Phase 8 — 산출물 생성 · Excel / Markdown

**1. 목표** — 대응표·체크리스트·기술질의서를 파일로 내보낸다.

**2. 구현할 기능** — FR-18, 19, 20, 21.

**3. 생성할 파일**
```
analysis/services/deliverables.py
analysis/prompts/draft_inquiry.txt
exports/services/{__init__,xlsx,markdown}.py
exports/{views,urls}.py
exports/tests/test_xlsx.py
```

**4. 수정할 파일** — `analysis/views.py` (deliverables), `requirements.txt` (openpyxl).

**5. 사용할 명령**
```powershell
# POST /api/runs/1/deliverables/  →  POST /api/runs/1/export/
pytest exports/tests -v
```

**6. 테스트 및 검증**
- 시트 3개 (`대응표` / `제출서류체크리스트` / `기술질의서`), 헤더 행 일치
- `GAP` 행의 사유·대체방안 열 채움 (공고 5.2)
- 제출서류 8건 상태 매핑 — 서류별 **1검색**, 발급 서류는 검색 없이 `need` 고정
- 한글 파일명 RFC 5987 인코딩

**7. 완료 조건** — `KPG-2025-EQ-0417_대응자료_YYYYMMDD.xlsx` 다운로드 성공,
기술질의서에 4.3·4.4·(3.1+3.2) 포함.

**09 검증 항목** — `test_xlsx_export_sheets` (§7.1),
`test_inquiry_covers_check_items` (§7.2), §6 "산출물".

---

## Phase 9 — 프론트 골격 · 지식베이스 · 검색 테스트 화면

**1. 목표** — 검색 점수 3개(결합/의미/키워드)를 눈으로 비교할 수 있다.

**2. 구현할 기능** — FR-08, 09, 12 (화면).

**3. 생성할 파일**
```
frontend/{package.json,vite.config.js,index.html}
frontend/src/{main.js,App.vue}
frontend/src/router/index.js
frontend/src/api/{client,knowledge}.js
frontend/src/stores/{knowledge,ui}.js
frontend/src/views/{KnowledgeView,KnowledgeSearchView}.vue
frontend/src/components/{StatusBadge,FileDropzone,ChunkTree}.vue
```

**4. 수정할 파일** — `.env.example` (`VITE_API_BASE_URL` 확인).

**5. 사용할 명령** — `cd frontend; npm install; npm run dev`

**6. 테스트 및 검증** — 예시 쿼리 버튼 3개 동작 · 공고문 업로드 시 경고 배너 +
서버 거부 메시지 표시 · 부모-자식 청크 계층 표시.

**7. 완료 조건** — `05-rag-pipeline.md` 6절 3개 쿼리를 화면에서 확인 가능.

**09 검증 항목** — §9 데모 순서 1번.

---

## Phase 10 — 입찰 건 · 문서 · 요구사항 화면

**1. 목표** — 업로드 → 추출 → 사람 검토 → 분석 실행 경로 완성.

**2. 구현할 기능** — FR-01, 02, 05, 06, 07, 22 (화면).

**3. 생성할 파일**
```
frontend/src/api/projects.js
frontend/src/stores/bid.js
frontend/src/views/{BidListView,BidDetailView}.vue
frontend/src/components/{DocumentsTab,RequirementsTab,InlineEditCell,
                         CategoryBadge,RagParamsForm}.vue
```

**4. 수정할 파일** — `frontend/src/router/index.js`.

**5. 사용할 명령** — `npm run dev`

**6. 테스트 및 검증** — 드롭존 2분리 · 추출 원문 표를 HTML `<table>` 로 원본 대조 ·
`warnings` 상단 노출(접지 않음) · `분석대상`/`채점대상` 토글 ·
가중치 슬라이더 합 1 연동.

**7. 완료 조건** — `총 17건 / 분석대상 17건 / 채점대상 13건` 표시, 분석 실행 시작.

**09 검증 항목** — §9 데모 순서 2·3·4번.

---

## Phase 11 — 결과 · 근거 · 정확도 · 산출물 화면

**1. 목표** — 판정을 근거까지 한 클릭으로 확인하고, 정확도·함정을 화면에서 읽는다.

**2. 구현할 기능** — FR-13~21, 23, 24 (화면).

**3. 생성할 파일**
```
frontend/src/api/{analysis,exports}.js
frontend/src/stores/analysis.js
frontend/src/composables/useRunPolling.js
frontend/src/components/{ResultsTab,ComplianceTable,VerdictBadge,EvidenceCard,
                         EvidenceModal,CrossIssueAlert,RunProgress,
                         AccuracyPanel,DeliverablesTab}.vue
```

**4. 수정할 파일** — `frontend/src/views/BidDetailView.vue`, `router/index.js`.

**5. 사용할 명령** — `npm run dev`

**6. 테스트 및 검증** — 폴링 2초·탭 이탈 시 정리 · **교차조항 alert 가 표 위에** ·
근거 0건이면 `MEET` 저장 버튼 비활성 (원칙 3 을 UI 에서도) ·
조항번호 숫자 튜플 정렬 · 함정 4개 O/X 체크리스트.

**7. 완료 조건** — 정확도 패널에 `11 / 13 (84.6%)` 형태 + 함정 4개 + 오답 상세 표시.

**09 검증 항목** — §9 데모 순서 5·6번, §6 전체 기준을 화면에서 확인.

---

## Phase 12 — 정확도 튜닝 루프

**1. 목표** — 10/13 → 13/13, 함정 3개 → 4개.

**2. 작업** — 프롬프트 수정 → `evaluate_run` → `09-acceptance-tests.md` 8절 기록표
한 줄 추가 → 반복.

**3. 생성할 파일** — 없음.

**4. 수정할 파일** — `analysis/prompts/*.txt`,
`specs/09-acceptance-tests.md` 8절, `README.md` 측정 기록.

**5. 사용할 명령** — `python manage.py evaluate_run --run-id N`

**6. 테스트 및 검증** — `prompt_versions` 해시로 어떤 프롬프트가 몇 점인지 추적.

**7. 완료 조건** — 목표 기준 도달, 또는 한계를 기록으로 남김.

**09 검증 항목** — §8 기록표가 채워짐, §9 데모 순서 7번.

---

## 3. FR 커버리지 확인

| Phase | FR |
|---|---|
| P0 | — |
| P1 | FR-02 (엔진) |
| P2 | FR-06, FR-22 (스모크) |
| P3 | FR-09 |
| P4 | FR-08, FR-10, FR-12 (API) |
| P5 | FR-01, FR-02(API), FR-03, FR-04, FR-05, FR-07(API), FR-22 |
| P6 | FR-11, FR-13, FR-14, FR-17 |
| P7 | FR-16, FR-24 |
| P8 | FR-18, FR-19, FR-20, FR-21 |
| P9 | FR-08, FR-09, FR-12 (화면) |
| P10 | FR-01, FR-05, FR-06, FR-07, FR-22 (화면) |
| P11 | FR-13~21, FR-23, FR-24 (화면) |
| P12 | — |

FR-01 ~ FR-24 전부 배정되었다. `00-overview.md` 3절의 비범위는 어느 Phase 에도 없다.

---

## 4. 09 인수 기준 → Phase 매핑

| 09 §7.1 테스트 (LLM 불필요) | Phase |
|---|---|
| `test_pdf_extract_tables` | P1 |
| `test_pdf_extract_announcement` | P1 |
| `test_clause_no_sorting` | P2 |
| `test_chunker_parent_child` | P3 |
| `test_chunker_model_tags` | P3 |
| `test_chunker_equipment_table` | P3 |
| `test_keyword_extraction` | P3 |
| `test_retriever_keyword_exact` | P4 |
| `test_retriever_model_filter` | P4 |
| `test_knowledge_rejects_bid_doc` | P4 |
| `test_source_doc_never_indexed` | P2(구조) → P5(완전) |
| `test_meet_without_evidence_rejected` | P6 |
| `test_meet_without_evidence_api` | P6 |
| `test_cross_clause_weight_conflict` | P7 |
| `test_cross_clause_lead_time` | P7 |
| `test_evaluator_scoring` | P7 |
| `test_xlsx_export_sheets` | P8 |

| 09 §7.2 테스트 (LLM 필요) | Phase |
|---|---|
| `test_extract_17_clauses` | P5 |
| `test_full_pipeline_accuracy` | P7 |
| `test_traps` | P7 |
| `test_inquiry_covers_check_items` | P8 |

| 함정 | 전제 Phase | 검증 Phase |
|---|---|---|
| TRAP-1 모델 혼동 | P3 (`model_tags`), P4 (모델 필터) | P6 |
| TRAP-2 선택사양 연쇄 효과 | P6 (`side_effects`) | **P7** (교차조항 패스 없이는 불가) |
| TRAP-3 실적 분류 | P3 (부문 헤딩) | P6 |
| TRAP-4 시험 부재 확인 | P3 (설비 현황표 행 청킹), P4 (`염수분무` 검색) | P6 |

`09-acceptance-tests.md` §6 합격 기준을 **전부 측정할 수 있게 되는 최초 시점은 P7** 이다.
