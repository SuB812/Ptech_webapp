"""Exact-match token extraction (specs/05-rag-pipeline.md section 3.4).

Regex, not an LLM. LLM keyword extraction would make indexing slow and
non-deterministic, and a re-index would shift the accuracy measurement under us.

Indexing and querying must normalise identically, or the ``keywords &&
ARRAY[...]`` overlap test silently never fires. ``normalize_token`` is the
single definition of that normalisation.
"""

from __future__ import annotations

import re

# Ordered most-specific first; overlapping matches are de-duplicated later.
PATTERNS: tuple[re.Pattern[str], ...] = (
    # 제품 모델: LT-150, LT-200
    re.compile(r"\bLT-\d{3}\b"),
    # 보호 등급: IP65, IP66
    re.compile(r"\bIP\d{2}\b"),
    # 문서/성적서/인증 번호: HB-CAT-2025-02, HB-T-2024-011, HB-QA-2025-07,
    # KSC-2022-1180, HE-2023-0471, KC-2022-0885, KSR-Q-2021-0339
    re.compile(r"\b[A-Z]{2,4}(?:-[A-Z]{1,3})?-\d{4}-\d{2,4}\b"),
    # 규격 번호: KS C 7658, KS C7658
    re.compile(r"\bKS\s?[A-Z]\s?\d{4}\b"),
    # ISO 9001:2015
    re.compile(r"\bISO\s?\d{4,5}(?::\d{4})?\b"),
    # 단위 수치: 140 W, 21,500 lm, 153 lm/W, 7.2 kg, 60,000 시간, -20℃, 120 MΩ, +12%
    re.compile(
        r"[\d,]+(?:\.\d+)?\s?"
        r"(?:lm/W|lm|W|K|kg|mm|시간|℃|MΩ|V|년|주|일|대|건|%)"
    ),
)

MODEL_RE = re.compile(r"\bLT-\d{3}\b")

_WS = re.compile(r"\s+")


def normalize_token(token: str) -> str:
    """Canonical form used on both sides of an exact match.

    Spaces and thousands separators go away and ASCII letters are upper-cased,
    so ``"20,000 lm"``, ``"20000 lm"`` and ``"20000LM"`` all collapse to the
    same token. Korean characters are unaffected.
    """
    return _WS.sub("", token).replace(",", "").upper()


def extract_keywords(*texts: str) -> list[str]:
    """Normalised exact-match tokens, de-duplicated.

    Grouped by pattern rather than by position in the text; the array-overlap
    test this feeds is order-independent.
    """
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for pattern in PATTERNS:
            for match in pattern.findall(text):
                token = normalize_token(match if isinstance(match, str) else match[0])
                if token and token not in seen:
                    seen.add(token)
                    found.append(token)
    return found


# KS test names are written with a "내~" (resistance-to) prefix -- 내염수분무,
# 내진동, 내전압, 내후성 -- while the equipment and reports they refer to are
# named without it (염수분무 시험기, 진동 시험기). Trigram matching does not
# bridge that one character, so the stripped form is probed as well.
_RESISTANCE_PREFIX = "내"


def build_item_probes(item: str) -> list[str]:
    """Keyword probe variants for a requirement item name.

    Not a morphological analyser (specs/05-rag-pipeline.md section 5.3 rules one
    out) -- just the one naming convention that decides clauses 4.3 and 4.4.
    Without the stripped form, ``내진동 시험`` never reaches
    ``진동 시험기: 미보유`` and TRAP-4 is unreachable.
    """
    item = (item or "").strip()
    if not item:
        return []

    probes = [item]
    if item.startswith(_RESISTANCE_PREFIX) and len(item) > 2:
        stripped = item[1:].strip()
        if stripped and stripped not in probes:
            probes.append(stripped)
    return probes


def extract_models(*texts: str) -> list[str]:
    """Product model codes mentioned in the given texts."""
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in MODEL_RE.findall(text):
            if match not in found:
                found.append(match)
    return found
