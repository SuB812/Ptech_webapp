"""The single gateway for every LLM and embedding call.

Nothing else in the project calls the OpenAI SDK directly
(specs/02-architecture.md section 5).

Two behaviours matter:

* ``temperature=0`` always, because verdict reproducibility is the point of the
  accuracy loop.
* ``settings.LLM_FAKE`` fakes *both* chat responses and embeddings, so the
  no-key test suite can exercise the retriever (section 5.1 of the same spec).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(settings.BASE_DIR) / "analysis" / "prompts"
FAKE_RESPONSES_DIR = Path(settings.BASE_DIR) / "analysis" / "fixtures" / "llm_responses"


class LLMUnavailable(RuntimeError):
    """No API key, or the provider failed. Maps to HTTP 503 `llm_unavailable`."""


class LLMResponseInvalid(RuntimeError):
    """The model returned something that is not the JSON we asked for."""


@dataclass
class LLMCall:
    """One call, recorded onto ``AnalysisRun.llm_calls``."""

    kind: str  # "chat" | "embedding"
    prompt_name: str
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    faked: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "prompt_name": self.prompt_name,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "faked": self.faked,
        }


@dataclass
class CallLog:
    """Accumulator handed through a pipeline run."""

    calls: list[LLMCall] = field(default_factory=list)

    def add(self, call: LLMCall) -> None:
        self.calls.append(call)

    def as_list(self) -> list[dict]:
        return [c.as_dict() for c in self.calls]

    @property
    def token_usage(self) -> dict:
        return {
            "prompt": sum(c.prompt_tokens for c in self.calls),
            "completion": sum(c.completion_tokens for c in self.calls),
        }


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def load_prompt(name: str) -> str:
    """Read ``analysis/prompts/<name>.txt``. Prompts never live inline in code."""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    """``sha1:<12 hex>`` for ``AnalysisRun.prompt_versions``.

    Without this we cannot say which prompt produced which accuracy score.
    """
    digest = hashlib.sha1(load_prompt(name).encode("utf-8")).hexdigest()
    return f"sha1:{digest[:12]}"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _client():
    if not settings.OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요.")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable(f"openai SDK 를 불러올 수 없습니다: {exc}") from exc
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def _fake_embedding(text: str, dim: int) -> list[float]:
    """Deterministic pseudo-embedding: same text always yields the same vector.

    It does NOT reproduce semantic similarity. Under LLM_FAKE only the keyword
    path, the weighted-sum formula, the model filter and the cutoffs are
    meaningful -- semantic ranking quality and accuracy need a real key
    (specs/02-architecture.md section 5.1).
    """
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_texts(texts: list[str], *, log: CallLog | None = None) -> list[list[float]]:
    """Embed a batch. Only child chunks are ever embedded.

    Batch size 64 with exponential backoff, per specs/05-rag-pipeline.md section 4.
    """
    if not texts:
        return []

    dim = settings.EMBEDDING_DIM
    model = settings.EMBEDDING_MODEL

    if settings.LLM_FAKE:
        started = time.monotonic()
        vectors = [_fake_embedding(t, dim) for t in texts]
        if log is not None:
            log.add(
                LLMCall(
                    kind="embedding",
                    prompt_name="-",
                    model=f"{model} (fake)",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    faked=True,
                )
            )
        return vectors

    client = _client()
    out: list[list[float]] = []
    batch_size = 64

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                began = time.monotonic()
                resp = client.embeddings.create(model=model, input=batch)
                elapsed = int((time.monotonic() - began) * 1000)
                out.extend([d.embedding for d in resp.data])
                if log is not None:
                    log.add(
                        LLMCall(
                            kind="embedding",
                            prompt_name="-",
                            model=model,
                            latency_ms=elapsed,
                            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
                        )
                    )
                break
            except Exception as exc:  # noqa: BLE001 - provider errors vary
                last_error = exc
                wait = 2**attempt
                logger.warning("embedding batch failed (attempt %s/3): %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(wait)
        else:
            raise LLMUnavailable(f"임베딩 호출이 3회 실패했습니다: {last_error}")

    if out and len(out[0]) != dim:
        raise LLMUnavailable(
            f"임베딩 차원 불일치: 모델이 {len(out[0])} 차원을 반환했으나 "
            f"EMBEDDING_DIM 은 {dim} 입니다. 모델을 되돌리거나 전체 재색인이 필요합니다."
        )
    return out


def embed_one(text: str, *, log: CallLog | None = None) -> list[float]:
    return embed_texts([text], log=log)[0]


# ---------------------------------------------------------------------------
# Chat (JSON only)
# ---------------------------------------------------------------------------


def _fake_chat_key(prompt_name: str, rendered: str) -> str:
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    return f"{prompt_name}.{digest}"


def _fake_chat_json(prompt_name: str, rendered: str) -> dict:
    """Look up a recorded response fixture.

    Keyed by prompt name + input hash so a prompt change invalidates the
    fixture instead of silently returning a stale answer.
    """
    exact = FAKE_RESPONSES_DIR / f"{_fake_chat_key(prompt_name, rendered)}.json"
    if exact.exists():
        return json.loads(exact.read_text(encoding="utf-8"))

    # Fall back to a per-prompt default so pipeline plumbing can be tested
    # before every input permutation has been recorded.
    default = FAKE_RESPONSES_DIR / f"{prompt_name}.default.json"
    if default.exists():
        return json.loads(default.read_text(encoding="utf-8"))

    raise LLMResponseInvalid(
        f"LLM_FAKE 응답 픽스처가 없습니다: {exact.name} 또는 {default.name} 를 "
        f"{FAKE_RESPONSES_DIR} 에 추가하세요."
    )


def chat_json(
    prompt_name: str,
    *,
    rendered_prompt: str,
    log: CallLog | None = None,
    model: str | None = None,
) -> dict:
    """Send a rendered prompt, require a JSON object back.

    One retry on a parse failure, then raise (specs/02-architecture.md section 5).
    """
    if settings.LLM_FAKE:
        started = time.monotonic()
        data = _fake_chat_json(prompt_name, rendered_prompt)
        if log is not None:
            log.add(
                LLMCall(
                    kind="chat",
                    prompt_name=prompt_name,
                    model=f"{model or settings.LLM_MODEL} (fake)",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    faked=True,
                )
            )
        return data

    client = _client()
    use_model = model or settings.LLM_MODEL
    last_error: Exception | None = None

    for attempt in range(2):
        began = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=use_model,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": rendered_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(f"LLM 호출 실패: {exc}") from exc

        elapsed = int((time.monotonic() - began) * 1000)
        usage = getattr(resp, "usage", None)
        if log is not None:
            log.add(
                LLMCall(
                    kind="chat",
                    prompt_name=prompt_name,
                    model=use_model,
                    latency_ms=elapsed,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
            )

        content = resp.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning("prompt %s returned non-JSON (attempt %s/2)", prompt_name, attempt + 1)
            continue

        if not isinstance(parsed, dict):
            last_error = LLMResponseInvalid("JSON 객체가 아닙니다.")
            continue
        return parsed

    raise LLMResponseInvalid(f"프롬프트 {prompt_name} 의 JSON 파싱이 2회 실패했습니다: {last_error}")
