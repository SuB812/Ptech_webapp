# 11. 개발 환경 구성

Windows 11 기준으로 적었다. macOS/Linux는 경로 구분자와 가상환경 활성화 명령만 다르다.

## 1. 사전 요구사항

| 항목 | 버전 | 확인 |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| PostgreSQL | 16+ | `psql --version` |
| pgvector | 0.7+ | 아래 2절 |

## 2. PostgreSQL + pgvector

### 2.1 확장 설치

Windows에서는 PostgreSQL 설치 후 [pgvector 릴리스](https://github.com/pgvector/pgvector)의
바이너리를 PostgreSQL `lib` / `share/extension` 에 넣는다.
StackBuilder에 없으므로 수동 설치가 필요하다.

### 2.2 DB 생성

```sql
CREATE DATABASE ptech ENCODING 'UTF8';
CREATE USER ptech WITH PASSWORD '설정한값';
GRANT ALL PRIVILEGES ON DATABASE ptech TO ptech;

\c ptech
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER SCHEMA public OWNER TO ptech;
```

확장 생성은 슈퍼유저 권한이 필요하다. 마이그레이션(`VectorExtension`)이 실패하면
위 SQL을 수동으로 먼저 실행한다.

### 2.3 확인

```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm');
```

## 3. 환경변수

```powershell
Copy-Item .env.example .env
```

`.env` 를 열어 채운다. **`.env` 는 커밋하지 않는다** (`.gitignore` 에 이미 있다).

| 변수 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | 예 | LLM·임베딩 호출용. 없으면 LLM 엔드포인트가 503 |
| `LLM_MODEL` | | 기본 `gpt-4o` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | | 기본 `text-embedding-3-small` / `1536`. **바꾸면 재색인 필수** |
| `POSTGRES_*` | 예 | DB 접속 정보 |
| `DJANGO_SECRET_KEY` | 예 | 아무 랜덤 문자열 |
| `RAG_*` | | 검색 기본 파라미터 (`05-rag-pipeline.md` 5.4) |
| `VITE_API_BASE_URL` | | 개발 중에는 `/api` (Vite 프록시) |

`DJANGO_SECRET_KEY` 생성:
```powershell
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## 4. 백엔드

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

`requirements.txt` (`02-architecture.md` 2절 기준):
```
Django>=5.0
djangorestframework
django-cors-headers
psycopg[binary]
pgvector
python-dotenv
pdfplumber
pypdf
openai
openpyxl
pytest
pytest-django
```

`http://localhost:8000/api/projects/` 가 빈 목록을 반환하면 정상이다.

## 5. 프론트엔드

```powershell
cd frontend
npm install
npm run dev
```

`http://localhost:5173` 에서 열린다. Vite 프록시가 `/api` 를 `:8000` 으로 넘긴다.

## 6. 초기 데이터 적재

지식베이스에 자사 자료를 넣는 관리 명령을 제공한다.

```powershell
cd backend
python manage.py load_knowledge ../samples/03_자사_제품카탈로그.md --kind catalog
python manage.py load_knowledge ../samples/04_자사_인증_시험_실적.md --kind qa
```

이 명령은 화면 업로드와 **같은 서비스 코드**를 호출한다 (별도 경로를 만들지 않는다).
LLM 임베딩 호출이 발생하므로 `OPENAI_API_KEY` 가 필요하다.

색인 확인:
```powershell
python manage.py shell -c "from knowledge.models import KnowledgeChunk as C; print(C.objects.count())"
```

샘플 입찰 건을 만드는 명령도 제공한다 (데모 준비용):
```powershell
python manage.py load_sample_bid
```
→ 입찰 건 생성 + `samples/01_입찰공고문.pdf`, `samples/02_기술사양서.pdf` 업로드.
요구사항 추출과 분석 실행은 하지 않는다 (사람이 화면에서 순서대로 확인하는 것이 데모의 요점).

## 7. 테스트

```powershell
cd backend
pytest                 # LLM 없는 테스트 (LLM_FAKE=True)
pytest -m llm          # LLM 호출 테스트 (API 키 필요, 비용 발생)
```

`pytest.ini`:
```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
markers =
    llm: 실제 LLM API를 호출하는 테스트 (비용 발생)
addopts = -m "not llm"
env =
    LLM_FAKE=True
```

기본 실행에서 `llm` 마커를 제외하는 이유: 실수로 비용이 발생하는 것을 막고, CI에서
API 키 없이 돌 수 있게 한다.

## 8. 정확도 측정 실행

```powershell
python manage.py evaluate_run --run-id 5
```
또는 화면의 `정확도 측정` 버튼 (`POST /api/runs/5/evaluate/`).

결과를 `specs/09-acceptance-tests.md` 8절 기록표와 `README.md` 에 반영한다.

## 9. 자주 겪는 문제

| 증상 | 원인 | 해결 |
|---|---|---|
| `type "vector" does not exist` | pgvector 확장 미설치 | 2.2절 SQL을 슈퍼유저로 실행 |
| 임베딩 저장 시 차원 오류 | `EMBEDDING_DIM` 과 컬럼 차원 불일치 | 모델을 되돌리거나 전체 재색인 |
| 표 추출이 어긋남 | `pdftotext` 계열 사용 | `pdfplumber.extract_tables()` 로 교체 (`05-rag-pipeline.md` 2.1) |
| 판정이 전부 `확인 필요` | 지식 색인 안 됨 / 임계값 과다 | 청크 수 확인, `threshold` 낮춰 재실행 |
| LT-200 값이 근거로 올라옴 | `model_tags` 미부여 또는 모델 필터 미적용 | 재색인 후 `model_filter` 확인 (TRAP-1) |
| `염수분무` 검색 0건 | 설비 현황표가 행 단위 청킹 안 됨 | 청커 수정 후 재색인 (TRAP-4 전제) |
| 한글 파일명 다운로드 깨짐 | `Content-Disposition` 인코딩 | RFC 5987 `filename*=UTF-8''` 사용 |
| CORS 에러 | `CORS_ALLOWED_ORIGINS` 누락 | `.env` 에 `http://localhost:5173` 추가 |
| 분석이 `running` 에서 멈춤 | 서버 재시작으로 스레드 소실 | 기동 시 정리 로직 확인 (`02-architecture.md` 3절) |

## 10. 커밋 전 확인

- [ ] `.env` 가 스테이징에 없다 (`git status` 확인)
- [ ] 새 환경변수를 `.env.example` 에 빈 값으로 추가했다
- [ ] `pytest` 통과
- [ ] 새 기능이 `specs/` 에 정의된 범위 안이다
- [ ] 실행 방법·의존성·기능 체크리스트가 바뀌었다면 `README.md` 갱신
- [ ] 프롬프트를 바꿨다면 정확도 재측정 후 `09-acceptance-tests.md` 8절에 기록
