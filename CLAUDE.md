# CLAUDE.md

발전소 입찰공고·기술사양서 분석 웹앱 (PoC). 이 파일은 코드를 쓰기 전에 반드시 읽는다.

## 0. 가장 중요한 규칙

1. **범위를 넓히지 않는다.** `specs/` 에 정의되지 않은 기능은 만들지 않는다.
   좋은 아이디어가 떠올라도 구현하지 말고 `specs/` 에 제안으로 적고 사용자에게 물어본다.
   특히 금지: 로그인/회원가입, 권한관리, 결제, 알림, 다국어, 실시간 협업, 채팅 UI,
   외부 나라장터 연동, 모바일 앱, Docker/K8s 배포 파이프라인.
2. **PoC다.** 목표는 "13개 항목 정답표 대조에서 정확도를 측정할 수 있는 상태"다.
   프로덕션 수준의 인증·확장성·캐싱·큐 인프라를 먼저 만들지 않는다.
3. **정확도가 기능보다 우선이다.** 화면을 늘리기 전에 `specs/09-acceptance-tests.md` 의
   13개 판정과 함정 4개가 통과하는지 확인한다.
4. **근거 없는 "충족" 판정은 버그다.** 판정 로직을 만질 때는 이 원칙을 깨지 않는지 본다.

## 1. 문서 지도

| 파일 | 내용 |
|---|---|
| `specs/00-overview.md` | 프로젝트 목적, 범위, 비범위, 용어 |
| `specs/01-functional-requirements.md` | 기능 요구사항 FR-01~ |
| `specs/02-architecture.md` | 아키텍처, 기술스택, 디렉터리 구조 |
| `specs/03-data-model.md` | Django 모델 / PostgreSQL 스키마 |
| `specs/04-api-spec.md` | REST API 엔드포인트 계약 |
| `specs/05-rag-pipeline.md` | 문서 추출, 청킹, 임베딩, 하이브리드 검색 |
| `specs/06-analysis-pipeline.md` | 요구사항 추출 → 항목별 판정 → 취합, LLM 프롬프트 |
| `specs/07-frontend-spec.md` | Vue 화면 및 컴포넌트 |
| `specs/08-sample-data.md` | 샘플 데이터 원문 정리 (구현 기준값) |
| `specs/09-acceptance-tests.md` | 정답표 13개, 함정 4개 시나리오, 정확도 측정 |
| `specs/10-output-templates.md` | 대응표, 체크리스트, 기술질의서, Excel 양식 |
| `specs/11-dev-setup.md` | 로컬 환경 구성, .env, 실행 명령 |

## 2. 기술 스택 (고정)

- Frontend: Vue 3 (Composition API, `<script setup>`), Vite, Bootstrap 5, SPA, Pinia, Vue Router
- Backend: Python 3.11+, Django 5, Django REST Framework, REST/JSON
- DB: PostgreSQL 16 + pgvector + pg_trgm
- LLM: GPT-4o 급 모델 (chat) + text-embedding-3-small (임베딩)
- PDF: pdfplumber (표 추출 필수), pypdf (메타데이터)

다른 라이브러리를 추가하려면 먼저 `specs/02-architecture.md` 의 의존성 목록에 추가하고,
왜 필요한지 한 줄 적는다. Celery/Redis 같은 인프라는 PoC에서 쓰지 않는다
(분석은 `AnalysisRun` 레코드 + 스레드 기반 백그라운드 실행으로 처리한다).

## 3. 절대 금지

- **API 키를 코드나 커밋에 넣지 않는다.** 모든 키는 `.env` 에서만 읽는다.
  `.gitignore` 에 `.env` 가 있는지 확인하고, 새 키를 추가하면 `.env.example` 에 빈 값으로 넣는다.
- 공고문/기술사양서를 RAG 지식베이스에 색인하지 않는다. 이 둘은 **입력**이고,
  지식베이스에 상주하는 것은 자사 자료(제품카탈로그, 인증·시험·실적)뿐이다.
  이 구분을 흐리는 코드는 잘못된 코드다.
- 요구사항 여러 개를 한 쿼리로 묶어 검색하지 않는다. **항목 하나당 검색 한 번.**
- `samples/` 의 파일을 수정하지 않는다. 읽기 전용 기준 데이터다.
- 판정 결과를 LLM이 만든 문장 그대로 신뢰해 저장하지 않는다. `verdict` 는 항상
  `MEET` / `GAP` / `CHECK` 세 값 중 하나로 검증한 뒤 저장한다.

## 4. 판정 3분류 (내부 값 고정)

| 내부 값 | 화면 표기 | 의미 |
|---|---|---|
| `MEET` | 충족 | 근거 문서로 요구조건을 만족함이 확인됨 |
| `GAP` | 보완 필요 | 근거는 찾았으나 요구조건에 미달 |
| `CHECK` | 확인 필요 | 근거를 못 찾음 / 자사 자료에 정보 없음 / 발주처 확인 필요 |

근거(`Evidence`)가 0건이면 `MEET` 를 저장할 수 없다. 서버에서 검증해 거부한다.

## 5. 작업 방식

- 한 번에 한 레이어씩 만든다: 모델 → 마이그레이션 → 추출 → RAG → 판정 → API → 화면.
  각 단계가 끝나면 `python manage.py test` 와 `specs/09-acceptance-tests.md` 의 해당 항목을 돌린다.
- LLM 프롬프트는 `backend/analysis/prompts/*.txt` 에 파일로 둔다. 코드에 인라인으로 박지 않는다.
  프롬프트를 바꾸면 정확도를 다시 측정하고 `specs/09-acceptance-tests.md` 의 기록표를 갱신한다.
- LLM 호출은 테스트에서 실제로 호출하지 않는다. `samples/` 기반 고정 응답 픽스처를 쓴다.
- 커밋 메시지는 한국어 한 줄 요약 + 필요시 본문. 사용자가 요청할 때만 커밋한다.

## 6. README 갱신 규칙

다음이 바뀌면 `README.md` 를 같은 커밋에서 갱신한다.
- 실행 방법, 환경변수, 의존성
- 구현 완료된 기능 체크리스트
- 정확도 측정 결과 (13개 중 몇 개)

## 7. 코드 규약

- Backend: Django 앱 단위로 분리 (`projects`, `documents`, `knowledge`, `analysis`, `exports`).
  뷰는 얇게, 로직은 `services.py` 에. DRF `ViewSet` + `Serializer` 사용.
- 모델 필드명·API 필드명은 영어 snake_case. 사용자에게 보이는 문자열만 한국어.
- Frontend: 컴포넌트 PascalCase, 파일 1컴포넌트. API 호출은 `src/api/*.js` 에만 둔다.
  Bootstrap 5 클래스를 쓰고 커스텀 CSS는 최소화한다.
- 타입/스키마 불일치를 막기 위해 API 응답 형태는 `specs/04-api-spec.md` 를 단일 기준으로 삼는다.
