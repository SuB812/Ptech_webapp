# 02. 아키텍처 및 기술 스택

## 1. 전체 구조

```
┌─────────────────────────────┐
│  Vue.js 3 SPA (Vite)        │
│  Bootstrap 5 / Pinia        │
│  :5173 (dev)                │
└──────────┬──────────────────┘
           │ HTTP / JSON  (CORS)
           ▼
┌─────────────────────────────┐        ┌──────────────────┐
│  Django 5 + DRF             │ ─────► │  LLM API         │
│  :8000                      │        │  gpt-4o          │
│                             │ ─────► │  embedding-3-sm  │
│  projects / documents /     │        └──────────────────┘
│  knowledge / analysis /     │
│  exports                    │
└──────────┬──────────────────┘
           │ Django ORM
           ▼
┌─────────────────────────────┐
│  PostgreSQL 16              │
│  + pgvector  (임베딩/유사도) │
│  + pg_trgm   (키워드 매칭)   │
└─────────────────────────────┘
```

파일(업로드 PDF, 생성된 xlsx)은 로컬 `MEDIA_ROOT` 에 저장한다. 오브젝트 스토리지는 비범위.

## 2. 기술 스택 (고정)

### Frontend
| 항목 | 선택 | 비고 |
|---|---|---|
| 프레임워크 | Vue 3 (Composition API, `<script setup>`) | |
| 빌드 | Vite 5 | dev 프록시로 `/api` → :8000 |
| UI | Bootstrap 5 + bootstrap-icons | 커스텀 CSS 최소화 |
| 상태 | Pinia | 입찰 건/분석 결과 스토어 |
| 라우팅 | Vue Router 4 | history 모드 |
| HTTP | axios | `src/api/` 에만 사용 |

### Backend
| 항목 | 선택 | 비고 |
|---|---|---|
| 런타임 | Python 3.11+ | |
| 프레임워크 | Django 5 + Django REST Framework | |
| PDF | pdfplumber | **표 추출 필수** |
| PDF 보조 | pypdf | 페이지 수·메타데이터 |
| 벡터 | pgvector + `django-pgvector` (또는 `pgvector.django`) | |
| LLM | `openai` SDK | GPT-4o 급 chat + embedding |
| Excel | openpyxl | |
| 설정 | python-dotenv | `.env` 로드 |
| CORS | django-cors-headers | |

### 의존성 추가 규칙
새 패키지가 필요하면 이 표에 한 줄(패키지명 + 왜 필요한지)을 먼저 추가한다.
아래는 **쓰지 않는다**: Celery, Redis, Elasticsearch, LangChain, LlamaIndex, Docker Compose 배포 구성.
(RAG 로직은 직접 구현한다. 프레임워크 추상화가 원칙 2·3을 흐리게 만든다.)

## 3. 비동기 처리 (큐 없이)

분석 파이프라인은 LLM 호출 수십 건으로 30초~2분이 걸린다. HTTP 요청을 붙잡지 않는다.

- `POST /api/runs/` 는 `AnalysisRun` 레코드를 `status=queued` 로 만들고 **202 + run_id** 를 즉시 반환.
- 실제 실행은 `threading.Thread` (daemon) 로 백그라운드 수행.
- 프론트는 `GET /api/runs/{id}/` 를 2초 간격 폴링해 진행률을 갱신한다.
- 진행률은 `processed_count / total_count` 와 `current_step` 으로 표현.
- 서버 재시작 시 `running` 상태로 남은 run은 `failed` 로 정리한다(기동 시 1회).

WebSocket/SSE는 비범위. Celery는 비범위. PoC에서 스레드로 충분하다.

## 4. 디렉터리 구조

```
Ptech_webapp/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── .env                       # 커밋 금지
├── samples/                   # 읽기 전용 기준 데이터
│   ├── 00_실습가이드_정답표.md
│   ├── 01_입찰공고문.pdf
│   ├── 02_기술사양서.pdf
│   ├── 03_자사_제품카탈로그.md
│   └── 04_자사_인증_시험_실적.md
├── specs/
│   └── 00~11 *.md
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/                # settings, urls, wsgi
│   │   ├── settings.py
│   │   └── urls.py
│   ├── projects/              # 입찰 건
│   │   ├── models.py serializers.py views.py urls.py
│   ├── documents/             # 입력 문서 + 추출
│   │   ├── models.py serializers.py views.py
│   │   ├── services/
│   │   │   ├── pdf_extract.py      # pdfplumber 텍스트/표 추출
│   │   │   └── requirement_extract.py  # LLM 요구사항 추출
│   ├── knowledge/             # RAG 지식베이스
│   │   ├── models.py serializers.py views.py
│   │   ├── services/
│   │   │   ├── chunker.py          # 부모-자식 청킹
│   │   │   ├── embedder.py         # 임베딩
│   │   │   └── retriever.py        # 하이브리드 검색
│   ├── analysis/              # 판정 파이프라인
│   │   ├── models.py serializers.py views.py
│   │   ├── services/
│   │   │   ├── pipeline.py         # 전체 오케스트레이션
│   │   │   ├── assessor.py         # 항목별 판정
│   │   │   ├── cross_clause.py     # 교차조항 검증
│   │   │   └── evaluator.py        # 정답표 대조 정확도
│   │   ├── prompts/
│   │   │   ├── extract_requirements.txt
│   │   │   ├── assess_requirement.txt
│   │   │   ├── cross_clause_check.txt
│   │   │   └── draft_inquiry.txt
│   │   └── fixtures/
│   │       └── answer_key.json     # 정답표 기계 판독형
│   ├── exports/               # Excel / Markdown 생성
│   │   ├── services/xlsx.py
│   │   └── views.py
│   └── common/
│       ├── llm.py             # LLM 클라이언트 래퍼 (재시도, JSON 검증)
│       └── enums.py           # Verdict, Category 등
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.js  App.vue  router/index.js
        ├── api/            # projects.js documents.js knowledge.js analysis.js
        ├── stores/         # project.js analysis.js knowledge.js
        ├── views/          # 화면 단위 (07-frontend-spec.md)
        └── components/     # 재사용 컴포넌트
```

## 5. LLM 호출 규약 (`common/llm.py`)

모든 LLM 호출은 이 래퍼를 거친다. 직접 `openai.chat.completions.create` 를 부르지 않는다.

- `temperature=0` 고정 (판정의 재현성이 중요하다).
- JSON 응답은 `response_format={"type":"json_object"}` 사용 + 스키마 검증.
- 파싱 실패 시 1회 재시도, 재시도도 실패하면 예외.
- 호출마다 `model`, `prompt_name`, `token_usage`, `latency_ms` 를 `AnalysisRun.llm_calls` 에 누적 기록.
- 프롬프트는 `analysis/prompts/*.txt` 에서 읽고 `.format()` 으로 값을 채운다.
- 테스트 환경(`settings.LLM_FAKE=True`)에서는 `samples/` 기반 고정 응답을 반환한다.

## 6. 설정 (`config/settings.py`)

`.env` 에서 읽는 값은 `.env.example` 에 전부 나열되어 있다. 하드코딩된 기본값으로
API 키를 대체하지 않는다. `OPENAI_API_KEY` 가 없으면 기동 시 경고를 출력하고
LLM이 필요한 엔드포인트만 503을 반환한다(화면·DB 작업은 동작해야 한다).

## 7. 에러 처리

- DRF 표준 형태 `{"detail": "...", "code": "..."}`.
- 사용자에게 보이는 메시지는 한국어, 로그는 영어 스택트레이스.
- LLM/DB 실패는 `AnalysisRun.status=failed` + `error_message` 에 남기고 프론트에서 재시도 버튼 제공.
