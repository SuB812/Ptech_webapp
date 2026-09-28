# 입찰·기술사양 분석 웹앱 (PoC)

발전소 입찰공고와 기술사양서(PDF)를 AI가 분석해 핵심 요구조건을 추출하고, 자사 제품사양·시험자료
(RAG 지식베이스)와 대조해 **충족 / 보완 필요 / 확인 필요** 를 근거와 함께 판정한 뒤,
기술규격 대응표·제출서류 체크리스트·기술질의서 초안을 생성하는 업무 지원 시스템.

> **현재 상태: 명세 작성 완료, 구현 미착수.**
> 구현을 시작하기 전에 [CLAUDE.md](CLAUDE.md) 와 [specs/](specs/) 를 읽는다.

---

## 무엇을 하는가

```
입찰공고문.pdf + 기술사양서.pdf
        │
        ▼  요구사항 자동 추출 (조항 단위)
   17개 조항  ── 사람이 확인·수정 ──┐
                                   ▼  항목 하나씩 개별 RAG 검색 + 판정
                            충족 7 / 보완 4 / 확인 필요 2
                                   │  + 조항 간 상충 검증
                                   ▼
                  대응표 · 제출서류 체크리스트 · 기술질의서 초안 → Excel
```

자사 자료(제품카탈로그, 인증·시험·실적)는 지식베이스에 **상주**하고, 공고문과 사양서는
입찰 건마다 바뀌는 **입력**이다. 이 구분이 설계의 출발점이다.

## 핵심 설계 원칙

1. **입력과 지식을 섞지 않는다** — 공고문·사양서는 벡터 색인하지 않는다.
2. **항목 하나당 검색 한 번** — 요구사항을 묶어 검색하면 벡터가 뭉개져 아무것도 못 찾는다.
3. **근거를 못 찾으면 "충족"이 아니다** — `확인 필요` 로 분류하고 기술질의서 후보로 넘긴다.
   근거 없는 `충족` 저장은 서버가 거부한다.
4. **판정은 3분류, 근거는 문서·위치까지 표시한다.**
5. **검색은 의미 + 키워드 하이브리드** — `LT-150`, `IP66` 같은 정확 매칭이 판정을 가른다.

원칙 2는 조항 간 상호작용을 구조적으로 못 잡는다. 그래서 **교차조항 검증**을 별도 패스로 둔다
([specs/06](specs/06-analysis-pipeline.md) 5절).

## 기술 스택

| 레이어 | 스택 |
|---|---|
| Frontend | Vue 3 (Composition API), Vite, Bootstrap 5, Pinia, Vue Router — SPA |
| Backend | Python 3.11+, Django 5, Django REST Framework — REST/JSON |
| Database | PostgreSQL 16 + pgvector (임베딩·유사도) + pg_trgm (키워드) |
| LLM | GPT-4o 급 chat + `text-embedding-3-small` |
| PDF | pdfplumber (표 추출), pypdf |

```
Vue.js SPA ──HTTP/JSON──▶ Django REST Framework ──Django ORM──▶ PostgreSQL + pgvector
```

## 명세 문서

구현의 단일 기준. 여기 정의되지 않은 기능은 만들지 않는다.

| 문서 | 내용 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 작업 규칙, 금지 사항, 문서 지도 |
| [specs/00-overview.md](specs/00-overview.md) | 목적, 범위, **비범위**, 핵심 원칙, 용어 |
| [specs/01-functional-requirements.md](specs/01-functional-requirements.md) | 기능 요구사항 FR-01 ~ FR-24 |
| [specs/02-architecture.md](specs/02-architecture.md) | 아키텍처, 스택, 디렉터리 구조 |
| [specs/03-data-model.md](specs/03-data-model.md) | Django 모델 / PostgreSQL 스키마 |
| [specs/04-api-spec.md](specs/04-api-spec.md) | REST API 계약 (프론트-백엔드 단일 기준) |
| [specs/05-rag-pipeline.md](specs/05-rag-pipeline.md) | PDF 추출, 부모-자식 청킹, 하이브리드 검색 |
| [specs/06-analysis-pipeline.md](specs/06-analysis-pipeline.md) | 추출 → 항목별 판정 → 교차검증 → 취합, **LLM 프롬프트** |
| [specs/07-frontend-spec.md](specs/07-frontend-spec.md) | 화면·컴포넌트·상태 관리 |
| [specs/08-sample-data.md](specs/08-sample-data.md) | 샘플 데이터 기준값 정리 |
| [specs/09-acceptance-tests.md](specs/09-acceptance-tests.md) | **정답표 13개, 함정 4개, 정확도 측정** |
| [specs/10-output-templates.md](specs/10-output-templates.md) | 대응표·체크리스트·기술질의서·Excel 양식 |
| [specs/11-dev-setup.md](specs/11-dev-setup.md) | 로컬 환경 구성, 실행, 트러블슈팅 |

## 샘플 데이터

`samples/` 는 가상 데모 데이터다. 발주처·기업명·성적서 번호 모두 실습용이며 민감정보가 없다.
**읽기 전용** — 수정하지 않는다.

| 파일 | 역할 |
|---|---|
| `01_입찰공고문.pdf` | 입력 — 발주처 공고 (KPG-2025-EQ-0417) |
| `02_기술사양서.pdf` | 입력 — 요구사항 원문 17개 조항 (KPG-2025-TS-0417) |
| `03_자사_제품카탈로그.md` | 지식 — LT-150 / LT-200 사양 (HB-CAT-2025-02) |
| `04_자사_인증_시험_실적.md` | 지식 — 인증·성적서·설비·실적 (HB-QA-2025-07) |
| `00_실습가이드_정답표.md` | 정확도 측정 기준 |

## 정확도 기준

이 PoC의 성공은 기능 개수가 아니라 숫자다. **"잘 되네요" 대신 "13개 중 11개 정확"** 이라고
말할 수 있어야 프롬프트를 고칠 근거가 생긴다.

| 기준 | 최소 | 목표 |
|---|---|---|
| 요구사항 추출 | 17개 조항 전부 | + 공고 참가자격 3건 |
| 판정 정확도 | 10 / 13 | 13 / 13 |
| 함정 통과 | 3 / 4 | 4 / 4 |
| 근거 없는 `충족` | **0건** (위반 시 불합격) | |
| 전체 실행 시간 | 3분 이내 | 2분 이내 |

### 심어둔 함정 4개

| ID | 이름 | 내용 |
|---|---|---|
| TRAP-1 | 모델 혼동 | 카탈로그에 LT-150과 LT-200이 나란히 있다. 150W급 요구에 LT-200 값(195W, 9.8kg)을 가져오면 오답 |
| TRAP-2 | 선택사양 연쇄 효과 | IP66 선택사양을 쓰면 무게가 7.2+1.4=8.6kg가 되어 8kg 제한 위반. 두 조항을 동시에 만족하는 조합이 없다 |
| TRAP-3 | 실적 분류 | 실적 총 9건이지만 발전 부문은 2건. "9건 보유, 충족"은 오답 |
| TRAP-4 | 시험 부재 확인 | 4.3·4.4는 "없다"를 판정해야 한다. 설비 현황에 "미보유" 명시가 있으므로 검색 실패와 실제 부재를 구분해야 한다 |

TRAP-2는 항목별 독립 판정 구조에서 **원리적으로 못 잡는다.** 교차조항 검증 패스가 필요하다.
이 함정이 RAG의 구조적 한계와 사람 검토가 필요한 이유를 보여준다.

### 측정 기록

프롬프트나 RAG 파라미터를 바꿀 때마다 갱신한다.
상세 기록: [specs/09-acceptance-tests.md](specs/09-acceptance-tests.md) 8절.

| 날짜 | 모델 | 정확도 | TRAP 1/2/3/4 | 메모 |
|---|---|---|---|---|
| — | — | — / 13 | — | 구현 전 |

## 빠른 시작

전체 절차와 트러블슈팅은 [specs/11-dev-setup.md](specs/11-dev-setup.md).

```powershell
# 0) 환경변수
Copy-Item .env.example .env     # OPENAI_API_KEY, POSTGRES_*, DJANGO_SECRET_KEY 채우기

# 1) DB (psql, 슈퍼유저)
#    CREATE DATABASE ptech ENCODING 'UTF8';
#    \c ptech
#    CREATE EXTENSION vector;  CREATE EXTENSION pg_trgm;

# 2) 백엔드
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver          # http://localhost:8000

# 3) 지식베이스 적재 (별도 터미널)
python manage.py load_knowledge ../samples/03_자사_제품카탈로그.md --kind catalog
python manage.py load_knowledge ../samples/04_자사_인증_시험_실적.md --kind qa

# 4) 프론트엔드 (별도 터미널)
cd frontend
npm install
npm run dev                         # http://localhost:5173
```

`.env` 는 **절대 커밋하지 않는다.** `.gitignore` 에 이미 포함되어 있다.

## 구현 진행 상황

| 영역 | FR | 상태 |
|---|---|---|
| 프로젝트 명세 | — | ✅ 완료 |
| DB 스키마 / 마이그레이션 | — | ⬜ |
| PDF 텍스트·표 추출 | FR-01, 02 | ⬜ |
| 요구사항 자동 추출 | FR-03 ~ 05 | ⬜ |
| 요구사항 분류·검토 화면 | FR-06, 07 | ⬜ |
| 지식베이스 업로드·청킹·임베딩 | FR-08, 09 | ⬜ |
| 하이브리드 검색 | FR-10 ~ 12 | ⬜ |
| 항목별 대조 판정 | FR-13 ~ 15 | ⬜ |
| 교차조항 검증 | FR-16 | ⬜ |
| 판정 수정 | FR-17 | ⬜ |
| 대응표·체크리스트·기술질의서 생성 | FR-18 ~ 20 | ⬜ |
| Excel / Markdown 다운로드 | FR-21 | ⬜ |
| 입찰 건·실행 이력 관리 | FR-22, 23 | ⬜ |
| 정확도 측정 | FR-24 | ⬜ |

## 범위 밖 (만들지 않는 것)

로그인·권한관리, 멀티테넌시, 나라장터 연동, 알림, 다국어, 스캔 PDF OCR, 원가·견적 계산,
Celery/Redis 작업 큐, Docker 배포 파이프라인, 모바일 앱, 문서 버전 비교.

전체 목록: [specs/00-overview.md](specs/00-overview.md) 3절.

## 데이터 및 보안

- 모든 샘플 데이터는 공개용 가상 데이터이며 민감정보·개인정보가 없다.
- LLM API 키는 `.env` 로만 관리한다. 코드·커밋에 넣지 않는다.
- 새 환경변수를 추가하면 `.env.example` 에 빈 값으로 함께 넣는다.
