# 03. 데이터 모델

PostgreSQL 16 + pgvector + pg_trgm. 모든 모델은 `created_at` / `updated_at` 을 가진다.

## 0. 확장 설치 (마이그레이션 0001)

```python
from pgvector.django import VectorExtension
from django.contrib.postgres.operations import TrigramExtension

operations = [VectorExtension(), TrigramExtension()]
```

## 1. Enum (`common/enums.py`)

```python
class DocType(models.TextChoices):        # 입력 문서 종류
    ANNOUNCEMENT = "announcement", "입찰공고문"
    TECHSPEC     = "techspec",     "기술사양서"

class KnowledgeKind(models.TextChoices):  # 지식 문서 종류
    CATALOG = "catalog", "제품카탈로그"
    QA      = "qa",      "인증·시험·실적"
    OTHER   = "other",   "기타"

class Category(models.TextChoices):       # FR-06
    DIMENSION     = "dimension",     "제품 치수"
    FILTER_GRADE  = "filter_grade",  "등급"
    EFFICIENCY    = "efficiency",    "효율"
    PRESSURE_DROP = "pressure_drop", "차압"
    TEST_STANDARD = "test_standard", "시험규격"
    CERTIFICATION = "certification", "인증"
    DELIVERY      = "delivery",      "납기"
    SUBMISSION    = "submission",    "제출서류"
    PERFORMANCE   = "performance",   "성능"
    MATERIAL      = "material",      "재질·구조"
    TRACK_RECORD  = "track_record",  "실적"
    OTHER         = "other",         "기타"

class Verdict(models.TextChoices):
    MEET  = "MEET",  "충족"
    GAP   = "GAP",   "보완 필요"
    CHECK = "CHECK", "확인 필요"

class EvidenceState(models.TextChoices):  # 근거 상태 — 함정 4 구분용
    FOUND_SUFFICIENT   = "found_sufficient",   "근거 확인, 충족"
    FOUND_INSUFFICIENT = "found_insufficient", "근거 확인, 미달"
    FOUND_ABSENT       = "found_absent",       "자사 자료에 미보유 명시"
    NOT_FOUND          = "not_found",          "근거 검색 실패"

class RunStatus(models.TextChoices):
    QUEUED  = "queued",  "대기"
    RUNNING = "running", "진행중"
    DONE    = "done",    "완료"
    FAILED  = "failed",  "실패"

class DocStatus(models.TextChoices):
    UPLOADED = "uploaded", "업로드됨"
    PARSING  = "parsing",  "추출중"
    PARSED   = "parsed",   "추출완료"
    INDEXING = "indexing", "색인중"
    INDEXED  = "indexed",  "색인완료"
    FAILED   = "failed",   "실패"

class SubmissionStatus(models.TextChoices):
    HAVE      = "have",      "보유"
    NEED      = "need",      "발급 필요"
    UNCERTAIN = "uncertain", "확인 필요"
```

---

## 2. `projects` 앱

### BidProject — 입찰 건

| 필드 | 타입 | 비고 |
|---|---|---|
| `id` | BigAuto | |
| `title` | CharField(300) | 사업명. 예: `○○화력발전소 구내 LED 투광등 교체` |
| `bid_no` | CharField(100), blank | 공고번호. 예: `KPG-2025-EQ-0417` |
| `org` | CharField(200), blank | 공고기관. 예: `한국발전기술공사 자재구매처` |
| `item_name` | CharField(200), blank | 구매품목. 예: `LED 투광등 150W급` |
| `quantity` | CharField(50), blank | 예: `200대` |
| `estimated_price` | CharField(100), blank | 원문 그대로. 예: `금 240,000,000원 (부가세 별도)` |
| `delivery_place` | CharField(300), blank | 예: `○○화력발전소 자재창고 (충청남도 소재)` |
| `delivery_term` | CharField(200), blank | 예: `계약체결일로부터 60일 이내` |
| `announced_on` | DateField, null | 공고일 |
| `inquiry_due_at` | DateTimeField, null | 기술질의 접수마감 |
| `bid_due_at` | DateTimeField, null | 입찰서 제출마감 |
| `opening_at` | DateTimeField, null | 개찰 |
| `spec_doc_no` | CharField(100), blank | 별첨 사양서 번호. 예: `KPG-2025-TS-0417` |
| `notes` | TextField, blank | 기타 사항 원문 |

`quantity` / `estimated_price` 를 문자열로 두는 이유: 공고 표기를 그대로 보존해 산출물에
원문으로 싣기 위함이다. 수치 연산은 하지 않는다 (원가·견적 계산은 비범위).

### ParticipationRequirement — 입찰 참가자격

| 필드 | 타입 | 비고 |
|---|---|---|
| `project` | FK(BidProject, related_name=`participation_reqs`) | |
| `seq` | CharField(20) | 예: `3.3` |
| `text` | TextField | 예: `최근 5년 이내 발전소 납품실적이 3건 이상인 자` |
| `status` | SubmissionStatus | 자사 충족 여부 |
| `note` | TextField, blank | |

### SubmissionItem — 제출서류 (FR-04)

| 필드 | 타입 | 비고 |
|---|---|---|
| `project` | FK(BidProject, related_name=`submission_items`) | |
| `seq` | IntegerField | 연번 1~8 |
| `name` | CharField(200) | 예: `KS 인증서 사본` |
| `note` | CharField(300), blank | 공고 비고 열 |
| `status` | SubmissionStatus | 기본 `uncertain` |
| `evidence_text` | TextField, blank | 매핑 근거. 예: `인증현황 1절 KSC-2022-1180` |
| `is_checked` | BooleanField(False) | 체크리스트 체크 상태 |

---

## 3. `documents` 앱

### SourceDocument — 입력 문서 (FR-01)

| 필드 | 타입 | 비고 |
|---|---|---|
| `project` | FK(BidProject, related_name=`documents`) | |
| `doc_type` | DocType | |
| `file` | FileField(upload_to=`bids/%Y/%m/`) | |
| `original_name` | CharField(300) | |
| `doc_no` | CharField(100), blank | 문서 내부 번호 |
| `page_count` | IntegerField(0) | |
| `status` | DocStatus | |
| `error_message` | TextField, blank | |

> **불변식**: `SourceDocument` 는 절대 `KnowledgeChunk` 를 갖지 않는다. 벡터 색인 대상이 아니다
> (원칙 1). 모델 레벨에 FK가 존재하지 않으므로 구조적으로 불가능해야 한다.

### DocumentPage — 페이지별 추출 결과

| 필드 | 타입 | 비고 |
|---|---|---|
| `document` | FK(SourceDocument, related_name=`pages`) | |
| `page_no` | IntegerField | 1-base |
| `text` | TextField | 표 밖 본문 |
| `tables` | JSONField(default=list) | `[{"index":0,"rows":[[...],...]}, ...]` |

`tables` 를 원본 2차원 배열로 보존하는 이유 두 가지. (1) LLM 추출이 틀렸을 때 사람이 원본 표를
대조할 수 있어야 한다. (2) 프롬프트를 바꿔 재추출할 때 PDF를 다시 파싱하지 않아도 된다.

### Requirement — 추출된 요구사항 (FR-03)

| 필드 | 타입 | 비고 |
|---|---|---|
| `project` | FK(BidProject, related_name=`requirements`) | |
| `source_document` | FK(SourceDocument, null) | |
| `clause_no` | CharField(30) | 예: `2.1`, `공고 3.3` |
| `chapter` | CharField(100), blank | 예: `제2장 성능 요구사항` |
| `category` | Category | |
| `item` | CharField(200) | 예: `소비전력` |
| `requirement_text` | TextField | 예: `150 W 이하` |
| `context_text` | TextField, blank | 표 밖 관련 서술 (예: 해안 2km 언급) |
| `source_page` | IntegerField, null | |
| `order` | IntegerField | 표시 순서 |
| `is_active` | BooleanField(True) | 분석 대상 여부 (FR-07) |
| `is_graded` | BooleanField(False) | 정확도 채점 대상 (FR-24) |
| `is_edited` | BooleanField(False) | 사람이 수정함 |
| `ai_item` / `ai_requirement_text` / `ai_category` | 원본 보존 | 수정 전 AI 값 |

제약: `unique_together = (project, clause_no, item)`.

---

## 4. `knowledge` 앱

### KnowledgeDocument — 자사 자료 (FR-08)

| 필드 | 타입 | 비고 |
|---|---|---|
| `title` | CharField(300) | 예: `한빛조명(주) 제품 카탈로그` |
| `doc_no` | CharField(100), blank | 예: `HB-CAT-2025-02` |
| `doc_kind` | KnowledgeKind | |
| `file` | FileField(upload_to=`knowledge/`) | `.pdf` 또는 `.md` |
| `revision_date` | DateField, null | 개정일 / 기준일 |
| `status` | DocStatus | |
| `chunk_count` | IntegerField(0) | |
| `embedding_model` | CharField(100) | 색인 시 사용한 모델 |
| `error_message` | TextField, blank | |

### KnowledgeChunk — 부모-자식 청크 (FR-09)

| 필드 | 타입 | 비고 |
|---|---|---|
| `document` | FK(KnowledgeDocument, related_name=`chunks`) | |
| `parent` | FK(self, null, related_name=`children`) | null이면 부모 청크 |
| `is_parent` | BooleanField | |
| `content` | TextField | 자식 = 검색 대상 단위, 부모 = 표/절 전체 |
| `section_path` | CharField(300) | 예: `2.2 구조 > 방수·방진 등급` |
| `heading` | CharField(300), blank | 예: `2.2 구조` |
| `page_no` | IntegerField, null | PDF 원본일 때 |
| `chunk_type` | CharField(20) | `table_row` / `table` / `text` / `heading` |
| `token_count` | IntegerField(0) | |
| `embedding` | VectorField(dim=1536), null | **자식 청크에만** 채운다 |
| `keywords` | ArrayField(CharField(60)) | 추출된 코드·등급·번호. 예: `["LT-150","IP65"]` |
| `model_tags` | ArrayField(CharField(30)) | 이 청크가 속한 제품 모델. 예: `["LT-150"]` |

인덱스:

```sql
CREATE INDEX ON knowledge_knowledgechunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON knowledge_knowledgechunk USING gin (content gin_trgm_ops);
CREATE INDEX ON knowledge_knowledgechunk USING gin (keywords);
CREATE INDEX ON knowledge_knowledgechunk USING gin (model_tags);
```

> `model_tags` 는 **함정 1 (모델 혼동) 방어 장치**다. LT-150 요구에 LT-200 청크가 근거로
> 올라오는 것을 검색 단계에서 감점·필터할 수 있게 한다. `specs/05-rag-pipeline.md` 5절 참조.

---

## 5. `analysis` 앱

### AnalysisRun — 분석 실행 (FR-23)

| 필드 | 타입 | 비고 |
|---|---|---|
| `project` | FK(BidProject, related_name=`runs`) | |
| `status` | RunStatus | |
| `current_step` | CharField(100), blank | 예: `항목별 판정 (7/17)` |
| `total_count` / `processed_count` | IntegerField | 진행률 |
| `llm_model` | CharField(100) | |
| `embedding_model` | CharField(100) | |
| `rag_params` | JSONField | `{"top_k":5,"threshold":0.4,"w_semantic":0.6,"w_keyword":0.4}` |
| `prompt_versions` | JSONField | `{"assess_requirement":"sha1:ab12..."}` 프롬프트 파일 해시 |
| `llm_calls` | JSONField(default=list) | 호출별 토큰·지연 기록 |
| `started_at` / `finished_at` | DateTimeField, null | |
| `error_message` | TextField, blank | |
| `summary` | JSONField | `{"MEET":7,"GAP":4,"CHECK":2,"total":13}` |
| `accuracy` | JSONField, null | FR-24 결과 |

`prompt_versions` 에 파일 해시를 남기는 이유: "프롬프트 고치고 재측정"이 이 PoC의 핵심 루프다.
어떤 프롬프트로 몇 점이 나왔는지 추적되지 않으면 개선 여부를 말할 수 없다.

### Assessment — 판정 (FR-13)

| 필드 | 타입 | 비고 |
|---|---|---|
| `run` | FK(AnalysisRun, related_name=`assessments`) | |
| `requirement` | FK(Requirement, related_name=`assessments`) | |
| `verdict` | Verdict | 현재값 (사람 수정 반영) |
| `ai_verdict` | Verdict | AI 원본. **정확도 측정은 이 값으로 한다** |
| `evidence_state` | EvidenceState | |
| `our_value` | CharField(300), blank | 예: `IP65` |
| `ai_our_value` | CharField(300), blank | |
| `rationale` | TextField | 판정 사유 |
| `gap_detail` | TextField, blank | 미달 내용. 예: `한 등급 미달` |
| `remedy` | TextField, blank | 대체방안. 예: `IP66 강화 하우징 선택사양 적용` |
| `remedy_side_effects` | JSONField(default=list) | 교차검증 입력. 예: `[{"field":"weight","op":"add","value":1.4,"unit":"kg"}]` |
| `confidence` | FloatField, null | 0~1 |
| `retrieval_query` | TextField | 실제 사용한 검색 쿼리 |
| `retrieved_chunk_ids` | JSONField(default=list) | 재현용 |
| `is_edited` | BooleanField(False) | |
| `edited_at` | DateTimeField, null | |

제약: `unique_together = (run, requirement)`.

**서버 검증 (FR-13, 원칙 3)**: `verdict == MEET` 이면서 `evidences.count() == 0` 인 저장은 거부한다.
serializer `validate()` 에서 막고, 파이프라인 내부에서는 예외 대신 `CHECK` 로 강제 전환하며
`evidence_state=not_found` 를 기록한다.

### Evidence — 근거 (FR-14)

| 필드 | 타입 | 비고 |
|---|---|---|
| `assessment` | FK(Assessment, related_name=`evidences`) | |
| `chunk` | FK(KnowledgeChunk, null, on_delete=SET_NULL) | |
| `doc_title` | CharField(300) | 스냅샷 |
| `doc_no` | CharField(100), blank | |
| `location` | CharField(300) | 예: `카탈로그 2.2 구조`, `성적서 HB-T-2024-011` |
| `page_no` | IntegerField, null | |
| `quote` | TextField | 인용 문장 |
| `parent_content` | TextField, blank | 모달용 부모 청크 전문 스냅샷 |
| `score` | FloatField | 결합 점수 |
| `semantic_score` / `keyword_score` | FloatField, null | |
| `rank` | IntegerField | 1-base |

근거를 스냅샷으로 복제해 두는 이유: 지식 문서를 재색인하면 청크 ID가 바뀐다. 과거 분석의
근거 표시가 깨지면 정확도 기록을 신뢰할 수 없다. `chunk` FK는 `SET_NULL` 로 두고
표시에는 스냅샷 필드를 쓴다.

### CrossClauseIssue — 교차조항 이슈 (FR-16)

| 필드 | 타입 | 비고 |
|---|---|---|
| `run` | FK(AnalysisRun, related_name=`cross_issues`) | |
| `clause_nos` | ArrayField(CharField(30)) | 예: `["3.1","3.2"]` |
| `requirements` | M2M(Requirement) | |
| `kind` | CharField(40) | `option_side_effect` / `mutually_exclusive` / `other` |
| `title` | CharField(300) | 예: `IP66 선택사양 적용 시 무게 제한 위반` |
| `description` | TextField | 계산 과정 포함. 예: `7.2 + 1.4 = 8.6kg > 8kg` |
| `severity` | CharField(20) | `high` / `medium` / `low` |
| `is_dismissed` | BooleanField(False) | 사용자가 무시 처리 |

### InquiryDraft — 기술질의서 초안 항목 (FR-20)

| 필드 | 타입 | 비고 |
|---|---|---|
| `run` | FK(AnalysisRun, related_name=`inquiries`) | |
| `seq` | IntegerField | |
| `clause_refs` | ArrayField(CharField(30)) | 예: `["3.1","3.2"]` |
| `source_kind` | CharField(20) | `check` / `gap_remedy` / `cross_clause` |
| `body` | TextField | 공문체 문안 |
| `ai_body` | TextField | 원본 |
| `is_included` | BooleanField(True) | 제외 토글 |
| `is_edited` | BooleanField(False) | |

### ExportFile — 생성된 산출물 (FR-21)

| 필드 | 타입 | 비고 |
|---|---|---|
| `run` | FK(AnalysisRun, related_name=`exports`) | |
| `kind` | CharField(20) | `xlsx` / `markdown` |
| `file` | FileField(upload_to=`exports/%Y/%m/`) | |
| `filename` | CharField(300) | |

---

## 6. 정답표 저장 (FR-24)

정답표는 DB 모델이 아니라 **픽스처 파일**로 둔다: `backend/analysis/fixtures/answer_key.json`.

이유: 정답표는 샘플 데이터에 종속된 테스트 자산이고 운영 데이터가 아니다. DB에 넣으면
"정답을 DB에서 조회해 판정에 참고"하는 오염 경로가 생긴다. 파일로 두고 `evaluator.py` 만
읽게 한다.

형식은 `specs/09-acceptance-tests.md` 4절에 정의한다. `evaluator.py` 는 `clause_no` 로
`Assessment.ai_verdict` 와 대조한다.

---

## 7. 관계도

```
BidProject ──┬─< SourceDocument ──< DocumentPage
             ├─< Requirement ──< Assessment >── AnalysisRun
             ├─< ParticipationRequirement           │
             ├─< SubmissionItem                     ├─< Evidence >─ KnowledgeChunk
             └─< AnalysisRun ───────────────────────┤
                                                    ├─< CrossClauseIssue
                                                    ├─< InquiryDraft
                                                    └─< ExportFile

KnowledgeDocument ──< KnowledgeChunk ──< KnowledgeChunk (parent → children)
```

`KnowledgeDocument` 는 `BidProject` 와 관계가 **없다.** 전역 상주 자산이다 (원칙 1).
