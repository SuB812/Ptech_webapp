# 11. 개발 환경 구성

Windows 11 기준으로 적었다. macOS/Linux는 경로 구분자와 가상환경 활성화 명령만 다르다.

## 1. 사전 요구사항

| 항목 | 버전 | 확인 |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| PostgreSQL | 16+ | `psql --version` |
| pgvector | 0.7+ | 아래 2절 |

### 1.1 현재 개발 PC 실측 (2026-09-28)

| 항목 | 상태 |
|---|---|
| Python | 3.12.0 ✔ |
| Node / npm | 24.20.0 / 11.19.0 ✔ |
| PostgreSQL | **16.15** 설치·실행 중, 5432 LISTEN ✔ |
| pgvector | **0.8.6 설치 완료** ✔ (아래 2.1 수동 설치 불필요) |
| pg_trgm | 기본 포함 ✔ |
| `psql` | **PATH 에 없음** → 전체 경로 사용 |

`psql` 은 PATH 에 등록되어 있지 않다. 이 문서의 모든 `psql` 호출은 전체 경로로 쓴다.

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' --version
```

매번 쓰기 번거로우면 세션 별칭을 만든다 (PATH 를 영구 수정하지 않아도 된다).

```powershell
Set-Alias psql 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
```

## 2. PostgreSQL + pgvector

### 2.1 확장 설치 (이 PC 에서는 완료됨)

> **현재 개발 PC 는 pgvector 0.8.6 이 이미 설치되어 있고 `CREATE EXTENSION vector` 도
> 확인되었다. 이 절은 건너뛴다.** 아래는 다른 PC 에 새로 구성할 때만 필요하다.

Windows 에서는 PostgreSQL 설치 후 [pgvector 릴리스](https://github.com/pgvector/pgvector)의
바이너리를 PostgreSQL `lib`(`vector.dll`) / `share/extension`(`vector.control`, `vector--*.sql`)
에 넣는다. StackBuilder 에 없으므로 수동 설치가 필요하다.

설치 여부 확인:
```powershell
Test-Path 'C:\Program Files\PostgreSQL\16\lib\vector.dll'
Test-Path 'C:\Program Files\PostgreSQL\16\share\extension\vector.control'
```

### 2.2 DB · role 생성 — `backend/db_init.sql`

DB 와 role 생성, 확장 설치를 한 스크립트로 묶어 두었다. 멱등하므로 두 번 실행해도 안전하다.

**`ptech` 비밀번호는 환경변수 `PTECH_DB_PASSWORD` 로 넘긴다.**
스크립트가 `\getenv` 로 읽는다. 파일·명령줄 인자·PowerShell 히스토리 어디에도 남지 않는다.

```powershell
# 1) 비밀번호를 입력받아 환경변수에 넣는다 (화면에 표시되지 않음)
$sec = Read-Host -AsSecureString 'New password for the ptech role'
$env:PTECH_DB_PASSWORD = [System.Net.NetworkCredential]::new('', $sec).Password

# 2) 실행 — postgres 슈퍼유저 비밀번호는 psql 이 직접 물어본다
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U postgres -h localhost -f backend\db_init.sql

# 3) .env 의 POSTGRES_PASSWORD 에 같은 값을 적은 뒤 환경변수를 지운다
Remove-Item Env:\PTECH_DB_PASSWORD
```

`Read-Host -AsSecureString` 을 쓰는 이유: 비밀번호를 명령줄에 직접 타이핑하면
PSReadLine 히스토리 파일(`ConsoleHost_history.txt`)에 평문으로 남는다.
이 방식은 입력값이 명령의 일부가 아니므로 히스토리에 기록되지 않는다.

#### 지켜야 할 제약

| 항목 | 이유 |
|---|---|
| **파일은 ASCII 전용** | 한글 Windows 콘솔에서 psql 의 `client_encoding` 이 UHC(CP949) 로 잡힌다. UTF-8 한글이 들어간 `-f` 스크립트는 UHC/UTF8 변환 오류로 죽는다. 주석·출력 메시지를 전부 영어로 둔 이유다 |
| **`\prompt` 를 쓰지 않는다** | `psql -f` 실행 시 stdin 이 터미널이 아니라 스크립트라 `could not read value for variable` 로 실패한다. 환경변수 + `\getenv` 가 유일하게 동작하는 방법이다 |
| **`-1` / `--single-transaction` 금지** | `CREATE DATABASE` 는 트랜잭션 블록 안에서 실행할 수 없다 |
| **`\getenv` 는 PostgreSQL 13+** | 이 프로젝트는 16 을 쓰므로 문제없다 |

#### 스크립트가 하는 일

1. `PTECH_DB_PASSWORD` 존재 확인 → 없으면 아무것도 바꾸지 않고 종료
2. 길이 8자 이상 확인 (서버로 나가는 것은 boolean 뿐, 비밀번호는 출력하지 않는다)
3. `SET log_statement = 'none'` — 클러스터가 `log_statement = ddl|all` 로 돌고 있어도
   `CREATE ROLE ... PASSWORD` 가 서버 로그에 남지 않게 한다
4. `vector` / `pg_trgm` 사용 가능 여부 출력
5. role `ptech` 생성 (**`CREATEDB` 필수** — `pytest-django` 가 `test_ptech` DB 를 만든다).
   이미 있으면 비밀번호·권한만 맞춘다. 직후 `\unset` 으로 psql 세션에서 지운다
6. database `ptech` 생성 (owner `ptech`, UTF8)
7. `\connect ptech` 후 `CREATE EXTENSION vector, pg_trgm`
   — **`postgres` DB 에만 만들어 두면 `ptech` 에서는 쓸 수 없다**
8. `ALTER SCHEMA public OWNER TO ptech` (PG15+ 는 public 스키마 CREATE 권한을 회수했다)
9. **`\connect template1` 후 `CREATE EXTENSION vector, pg_trgm`** — 아래 2.4절
10. 최종 확인 출력 — encoding UTF8, 확장 2행, `rolcreatedb = t`

### 2.4 `template1` 에 확장이 필요한 이유 (테스트 필수)

`pytest-django` 는 실행마다 `test_ptech` DB 를 **`ptech` role 권한으로** 새로 만들고
그 안에서 마이그레이션을 돌린다. 이때 `CREATE EXTENSION vector` 가 실패한다.

```
django.db.utils.ProgrammingError: permission denied to create extension "vector"
HINT: Must be superuser to create this extension.
```

원인은 확장의 `trusted` 플래그 차이다.

| 확장 | `trusted` | 비슈퍼유저가 설치 가능? |
|---|---|---|
| `pg_trgm` | `true` (기본 제공) | **가능** — DB 소유자면 된다 |
| `vector` | 없음 (pgvector 0.8.6 `vector.control` 확인) | **불가** — 슈퍼유저만 |

`ptech` 는 `CREATEDB` 는 있지만 슈퍼유저가 아니므로, 자기가 만든 `test_ptech` 에도
`vector` 를 넣을 수 없다.

해결: **확장을 `template1` 에 넣는다.** 새 DB 는 `template1` 을 복제해 만들어지므로
`test_ptech` 는 생성 시점에 이미 확장을 갖고 있고, 마이그레이션의
`CREATE EXTENSION IF NOT EXISTS` 는 존재 확인 단계에서 조용히 넘어간다
(PostgreSQL 은 중복 검사를 권한 검사보다 먼저 한다).

```powershell
# db_init.sql 을 이미 실행했고 이 단계만 추가하는 경우
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U postgres -h localhost -d template1 `
  -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

**이것은 클러스터 전체에 영향을 준다.** 이후 이 클러스터에 만드는 모든 DB 가 두 확장을
갖게 된다. 개발 PC 에서는 문제없고 pgvector 문서도 권장하는 방식이다. 되돌리려면:

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U postgres -h localhost -d template1 `
  -c "DROP EXTENSION vector, pg_trgm;"
```

대안으로 `vector.control` 에 `trusted = true` 를 추가하는 방법도 있으나,
벤더 파일을 수정하는 것이고 pgvector 업그레이드 시 사라진다. 채택하지 않았다.

### 2.3 확인

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\psql.exe' -U ptech -h localhost -d ptech `
  -c "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm');"
```

`vector` 와 `pg_trgm` 두 행이 나오면 정상이다.

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
pytest-env
```

`pytest-env` 는 `pytest.ini` 의 `env =` 섹션을 제공하는 플러그인이다.
이것이 없으면 `LLM_FAKE=True` 가 테스트에 적용되지 않고, 키 없는 테스트가
실제 API 를 호출하려 해서 실패한다 (`02-architecture.md` 2절).

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

### 6.1 채점 대상 지정

요구사항 추출 후, 정답표의 13개 조항에 `is_graded` 를 켠다.

```powershell
python manage.py mark_graded --project 1
```

추출 단계는 `is_graded` 를 건드리지 않는다. 정답표 픽스처를 읽는 코드를
`evaluator.py` 와 이 명령 둘로 한정하기 위함이다 (`03-data-model.md` 6.1절).
실제 입찰 건에는 정답표가 없으므로 FR-07 화면에서 직접 토글한다.

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
| `psql: command not found` | PATH 미등록 | 전체 경로 사용 (1.1절) |
| `character with byte sequence 0x... in encoding "UHC" has no equivalent in "UTF8"` (또는 그 반대) | 한글 Windows 콘솔의 `client_encoding` 이 UHC 인데 `-f` 스크립트가 UTF-8 한글을 담고 있음 | **SQL 스크립트를 ASCII 전용으로 유지한다.** `db_init.sql` 은 그래서 영어로만 쓰여 있다. 한글이 꼭 필요하면 스크립트 첫 줄에 `\encoding UTF8` 을 넣는다 |
| `\prompt: could not read value for variable` | `psql -f` 실행 시 stdin 이 터미널이 아니다 | `\prompt` 대신 환경변수 + `\getenv` 를 쓴다 (2.2절) |
| `:'ptech_pw'` 가 그대로 SQL 에 들어가 구문 오류 | `PTECH_DB_PASSWORD` 미설정 또는 `\getenv` 미지원(PG 12 이하) | 환경변수를 설정한다. psql 13+ 인지 `psql --version` 으로 확인한다 |
| `ERROR: environment variable PTECH_DB_PASSWORD is not set.` | 의도된 안전 종료 | 2.2절 1단계를 먼저 실행한다. DB 는 변경되지 않았다 |
| `type "vector" does not exist` | 확장이 `ptech` DB 에 없음 | `db_init.sql` 재실행. `postgres` DB 에만 만들어도 `ptech` 에는 적용되지 않는다 |
| `CREATE DATABASE cannot run inside a transaction block` | `psql -1` 사용 | `-1` 없이 실행 (2.2절) |
| `permission denied for schema public` (마이그레이션) | PG15+ 의 public 스키마 권한 | `db_init.sql` 8단계가 처리한다. 재실행 |
| `permission denied to create database` (pytest) | role 에 `CREATEDB` 없음 | `db_init.sql` 재실행 (5단계가 `ALTER ROLE` 로 보정한다) |
| `permission denied to create extension "vector"` (pytest 의 테스트 DB 생성 중) | `vector` 는 trusted 확장이 아니라 슈퍼유저만 설치할 수 있고, `test_ptech` 는 `ptech` 권한으로 만들어진다 | 확장을 `template1` 에 넣는다 — **2.4절** |
| `LLM_FAKE` 가 안 먹고 실제 API 호출 | `pytest-env` 미설치 | `pip install pytest-env` (4절) |
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
