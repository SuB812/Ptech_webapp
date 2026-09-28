"""Hybrid retrieval (FR-10, specs/05-rag-pipeline.md section 5).

Semantic search alone cannot separate ``IP66`` from ``IP65``, or ``LT-150`` from
``LT-200`` -- in vector space those strings sit almost on top of each other, yet
one character decides the verdict. So keyword matching is mixed in at
0.6 / 0.4 (semantic / keyword).

Returning zero hits is a correct outcome, not a failure. The threshold is
deliberately generous and an empty result must fall through to CHECK rather than
be padded by lowering it (principle 3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.db.models import F, Value
from django.db.models.functions import Concat, Greatest
from pgvector.django import CosineDistance

from common.llm import CallLog, embed_one
from knowledge.models import KnowledgeChunk
from knowledge.services.keywords import (
    build_item_probes,
    extract_keywords,
    extract_models,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievalHit:
    chunk: KnowledgeChunk  # child
    parent: KnowledgeChunk | None
    score: float
    semantic_score: float
    keyword_score: float
    rank: int = 0

    @property
    def doc_title(self) -> str:
        return self.chunk.document.title

    @property
    def doc_no(self) -> str:
        return self.chunk.document.doc_no

    @property
    def location(self) -> str:
        """Last one or two path segments, for display (05 section 3.3)."""
        parts = [p for p in self.chunk.section_path.split(" > ") if p]
        return " ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")

    @property
    def parent_content(self) -> str:
        return self.parent.content if self.parent else self.chunk.content

    @property
    def model_tags(self) -> list[str]:
        return self.chunk.model_tags


def _semantic_scores(qvec: list[float], pool: int) -> dict[int, float]:
    rows = (
        KnowledgeChunk.objects.filter(is_parent=False, embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", qvec))
        .order_by("distance")
        .values_list("id", "distance")[:pool]
    )
    # Cosine distance in [0, 2]; 1 - d gives the usual similarity.
    return {cid: max(0.0, 1.0 - float(d)) for cid, d in rows}


def _haystack():
    """The text keyword matching runs against: content plus its heading path.

    Deliberately the same text that gets embedded (specs/05-rag-pipeline.md
    section 4). A delivery record row never says "납품실적" -- only its path does
    (``... > 4. 최근 5년 납품실적 > 4.1 발전 부문``), so matching content alone
    loses clause 5.4 entirely.

    Trade-off: a computed expression cannot use the GIN index on ``content``.
    At PoC corpus size (under 100 children) that is irrelevant; at scale this
    would become a stored generated column.
    """
    return Concat(F("content"), Value(" "), F("section_path"))


def _keyword_scores_multi(
    probes: list[str], tokens: list[str], pool: int
) -> dict[int, float]:
    """Best keyword score across several probe texts.

    A composed requirement query dilutes trigram matching: ``내염수분무 시험 염해
    환경 대응, 240시간`` scores below threshold against
    ``... 염수분무 시험기: 미보유`` even though ``내염수분무 시험`` alone scores 0.875.
    The item name is the discriminating noun phrase, so it is probed separately
    and the better score wins. Measured effect: clauses 4.3 and 4.4 go from
    "no evidence at all" to retrieved, which is what TRAP-4 depends on.
    """
    merged: dict[int, float] = {}
    for probe in probes:
        if not probe or not probe.strip():
            continue
        for cid, score in _keyword_scores(probe, tokens, pool).items():
            if score > merged.get(cid, 0.0):
                merged[cid] = score
    return merged


def _keyword_scores(query: str, tokens: list[str], pool: int) -> dict[int, float]:
    """Trigram similarity, word similarity and exact token overlap, whichever wins.

    ``word_similarity`` is what makes a narrow term work: ``염수분무 시험`` against
    ``3. 시험 설비 보유 현황 — 염수분무 시험기: 미보유`` scores poorly on whole-string
    similarity but highly on the best-matching extent. Without it TRAP-4 relies
    on semantics alone.

    Exact overlap scores 1.0, and that is what separates IP66 from IP65.
    """
    haystack = _haystack()

    rows = (
        KnowledgeChunk.objects.filter(is_parent=False)
        .annotate(
            keyword_score=Greatest(
                TrigramSimilarity(haystack, query),
                TrigramWordSimilarity(query, haystack),
            )
        )
        .order_by("-keyword_score")
        .values_list("id", "keyword_score")[:pool]
    )
    scores = {cid: float(s or 0.0) for cid, s in rows}

    # Exact token overlap is a separate, cheap query so the 1.0 cannot be lost
    # to the pool cut-off above.
    if tokens:
        for cid in (
            KnowledgeChunk.objects.filter(is_parent=False)
            .filter(keywords__overlap=tokens)
            .values_list("id", flat=True)
        ):
            scores[cid] = 1.0

    return scores


def search(
    query: str,
    *,
    keyword_probes: list[str] | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
    w_semantic: float | None = None,
    w_keyword: float | None = None,
    model_filter: str | None = None,
    doc_kinds: list[str] | None = None,
    log: CallLog | None = None,
) -> list[RetrievalHit]:
    """One hybrid search for one requirement (principle 2).

    ``query`` drives the semantic half and carries the full context.
    ``keyword_probes`` are extra texts for the keyword half only -- typically the
    bare item name, which discriminates far better than the composed query. Only
    one embedding is computed, so this is still one retrieval per requirement.
    """
    top_k = settings.RAG_TOP_K if top_k is None else top_k
    threshold = settings.RAG_SCORE_THRESHOLD if threshold is None else threshold
    w_semantic = settings.RAG_SEMANTIC_WEIGHT if w_semantic is None else w_semantic
    w_keyword = settings.RAG_KEYWORD_WEIGHT if w_keyword is None else w_keyword
    pool = settings.RAG_CANDIDATE_POOL

    query = (query or "").strip()
    if not query:
        return []

    query_models = extract_models(query)
    if model_filter is None:
        # A model named in the query is promoted to a filter.
        model_filter = query_models[0] if len(query_models) == 1 else None

    # Model codes are removed from the exact-match token set on purpose. Leaving
    # them in makes every chunk of that model score a flat 1.0, which flattens
    # the ranking: for clause 5.4 a test-report metadata chunk outranked the
    # delivery records. Model identity belongs to the filter below, not to
    # keyword scoring.
    tokens = [t for t in extract_keywords(query) if t not in query_models]

    qvec = embed_one(query, log=log)

    probes = [query, *(keyword_probes or [])]
    semantic = _semantic_scores(qvec, pool)
    keyword = _keyword_scores_multi(probes, tokens, pool)

    candidate_ids = set(semantic) | set(keyword)
    if not candidate_ids:
        return []

    chunks = {
        c.id: c
        for c in KnowledgeChunk.objects.filter(id__in=candidate_ids)
        .select_related("document", "parent")
    }
    if doc_kinds:
        chunks = {
            cid: c for cid, c in chunks.items() if c.document.doc_kind in doc_kinds
        }

    scored: list[RetrievalHit] = []
    for cid, chunk in chunks.items():
        s = semantic.get(cid, 0.0)
        k = keyword.get(cid, 0.0)
        score = w_semantic * s + w_keyword * k

        if model_filter:
            tags = chunk.model_tags or []
            if not tags:
                pass  # common information, never penalised
            elif model_filter in tags:
                score += settings.RAG_MODEL_MATCH_BONUS
            else:
                # Demoted hard, but not dropped: the user must be able to see
                # that an LT-200 value surfaced, and the tagging could be wrong.
                score *= settings.RAG_MODEL_MISMATCH_FACTOR

        scored.append(
            RetrievalHit(
                chunk=chunk,
                parent=chunk.parent,
                score=round(score, 6),
                semantic_score=round(s, 6),
                keyword_score=round(k, 6),
            )
        )

    scored.sort(key=lambda h: h.score, reverse=True)

    # Diversity: cap how many children of one parent may occupy the top_k.
    #
    # One 성적서 section contributes four near-identical children (기관 / 일자 /
    # 시험품 metadata plus rows). Left unchecked they took four of the five slots
    # for clause 4.4 and pushed the "진동 시험기: 미보유" row out entirely -- the
    # one piece of evidence TRAP-4 needs. The parent is delivered once anyway
    # (specs/05-rag-pipeline.md 5.3-6), so extra siblings buy nothing.
    max_per_parent = settings.RAG_MAX_PER_PARENT
    per_parent: dict[int, int] = {}
    kept: list[RetrievalHit] = []
    for hit in scored:
        if hit.score < threshold:
            continue
        key = (hit.parent or hit.chunk).id
        if per_parent.get(key, 0) >= max_per_parent:
            continue
        per_parent[key] = per_parent.get(key, 0) + 1
        kept.append(hit)
        if len(kept) >= top_k:
            break

    for rank, hit in enumerate(kept, start=1):
        hit.rank = rank

    logger.debug(
        "search %r -> %s/%s hits (model_filter=%s)",
        query, len(kept), len(scored), model_filter,
    )
    return kept


# Categories where the product model must not filter the evidence.
#
# Past contracts are not model-scoped: the announcement asks for power-plant
# deliveries, and 09 TRAP-3 calls excluding the 2024 LT-200 record "과도한 축소",
# an error. Certifications and submission documents are company-level too.
MODEL_FILTER_EXEMPT_CATEGORIES = {"track_record", "certification", "submission"}


def retrieve_for_requirement(
    *,
    item: str,
    requirement_text: str = "",
    category: str = "",
    model_hint: str | None = None,
    **kwargs,
) -> list[RetrievalHit]:
    """Retrieval policy for one requirement: retrieve by what it is, judge by what it must be.

    The semantic query is the **item name alone**. Our own documents never
    contain the buyer's wording, so folding ``requirement_text`` into the
    embedding query only dilutes it -- measured on all 18 sample clauses, the
    composed query lost the evidence for 4.3 and 4.4 entirely while the item
    alone lost none.

    ``requirement_text`` still drives keyword matching, where its exact tokens
    (``IP66``, ``8 kg``) are decisive, alongside the item and its prefix variants.
    """
    item = (item or "").strip()
    if not item:
        return []

    probes: list[str] = []
    composed = f"{item} {requirement_text}".strip()
    if composed != item:
        probes.append(composed)
    probes.extend(build_item_probes(item))

    if category in MODEL_FILTER_EXEMPT_CATEGORIES:
        model_hint = None

    return search(item, keyword_probes=probes, model_filter=model_hint, **kwargs)


def unique_parents(hits: list[RetrievalHit]) -> list[KnowledgeChunk]:
    """Parents behind the hits, de-duplicated, best-scoring first.

    Several children of one table often match; the LLM should see that table
    once (specs/05-rag-pipeline.md 5.3-6).
    """
    seen: set[int] = set()
    out: list[KnowledgeChunk] = []
    for hit in hits:
        parent = hit.parent or hit.chunk
        if parent.id in seen:
            continue
        seen.add(parent.id)
        out.append(parent)
    return out
