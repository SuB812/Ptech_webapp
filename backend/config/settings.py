"""Django settings for the Ptech bid-analysis PoC.

Every configurable value comes from ``.env`` (see ``.env.example``).
Hardcoded fallbacks are never used for secrets: a missing ``OPENAI_API_KEY``
degrades LLM endpoints to 503 but must not break DB or UI work
(specs/02-architecture.md section 6).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# .env lives next to manage.py; fall back to the repo root for convenience.
load_dotenv(BASE_DIR / ".env")
load_dotenv(REPO_ROOT / ".env")

SAMPLES_DIR = REPO_ROOT / "samples"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Core -------------------------------------------------------------------

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

if not SECRET_KEY:
    if DEBUG:
        # Unusable in production, but lets `manage.py check` and tests run
        # before the developer has filled in .env.
        SECRET_KEY = "django-insecure-poc-placeholder-set-DJANGO_SECRET_KEY-in-env"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Needed for ArrayField GIN indexes, TrigramExtension and the
    # TrigramSimilarity lookup used by the hybrid retriever (Phase 4).
    "django.contrib.postgres",
    "rest_framework",
    "corsheaders",
    "projects",
    "documents",
    "knowledge",
    "analysis",
    "exports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "ptech"),
        "USER": os.getenv("POSTGRES_USER", "ptech"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}
# The test database is cloned from template1, which is why db_init.sql installs
# vector and pg_trgm there: pgvector is not a "trusted" extension, so the
# non-superuser ptech role cannot create it inside its own test database
# (specs/11-dev-setup.md section 2.4).

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- i18n / files -----------------------------------------------------------

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- DRF --------------------------------------------------------------------
# No authentication: the PoC is single-user (specs/00-overview.md section 3).

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# --- LLM --------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_TEMPERATURE = env_float("LLM_TEMPERATURE", 0.0)
LLM_MAX_TOKENS = env_int("LLM_MAX_TOKENS", 4096)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = env_int("EMBEDDING_DIM", 1536)

# When true, common.llm returns deterministic fake chat responses AND fake
# embeddings so the suite runs without an API key
# (specs/02-architecture.md section 5.1).
LLM_FAKE = env_bool("LLM_FAKE", False)

# --- RAG defaults (specs/05-rag-pipeline.md section 5.4) --------------------

RAG_TOP_K = env_int("RAG_TOP_K", 5)
RAG_SCORE_THRESHOLD = env_float("RAG_SCORE_THRESHOLD", 0.4)
RAG_SEMANTIC_WEIGHT = env_float("RAG_SEMANTIC_WEIGHT", 0.6)
RAG_KEYWORD_WEIGHT = env_float("RAG_KEYWORD_WEIGHT", 0.4)
RAG_CANDIDATE_POOL = env_int("RAG_CANDIDATE_POOL", 40)
RAG_MODEL_MISMATCH_FACTOR = env_float("RAG_MODEL_MISMATCH_FACTOR", 0.3)
RAG_MODEL_MATCH_BONUS = env_float("RAG_MODEL_MATCH_BONUS", 0.1)
# Diversity cap: how many children of one parent may fill the top_k.
RAG_MAX_PER_PARENT = env_int("RAG_MAX_PER_PARENT", 2)

# --- Upload limits (specs/01-functional-requirements.md FR-01) --------------

UPLOAD_MAX_BYTES = env_int("UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
UPLOAD_MAX_PAGES = env_int("UPLOAD_MAX_PAGES", 50)

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
