"""Clause-number ordering.

Clause numbers are strings, and string ordering is wrong for them: ``"2.10"``
sorts before ``"2.2"`` lexicographically. Every list shown to a user, every
matrix row and every export must use numeric-tuple ordering instead
(specs/07-frontend-spec.md 2.4, specs/10-output-templates.md 1.1).
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+")
# Punctuation that merely separates the numeric parts, not a real prefix.
_SEPARATORS = " .·-_()[]/:,"


def clause_sort_key(clause_no: str | None) -> tuple[int, str, tuple[int, ...]]:
    """Sort key for a clause number.

    Ordering, in three tiers:

    1. plain spec clauses (``2.1``, ``2.10``, ``3.1``) in numeric order;
    2. prefixed clauses (``공고 3.3``) grouped by prefix -- these come from the
       announcement rather than the spec sheet and belong after it;
    3. anything with no digits at all, last.

    >>> sorted(["2.10", "2.2", "공고 3.3", "3.1"], key=clause_sort_key)
    ['2.2', '2.10', '3.1', '공고 3.3']
    """
    text = (clause_no or "").strip()
    numbers = tuple(int(n) for n in _NUM.findall(text))
    prefix = _NUM.sub("", text).strip(_SEPARATORS)

    if not numbers:
        return (2, prefix, ())
    return (1 if prefix else 0, prefix, numbers)


def sort_by_clause(items, key=lambda x: x):
    """Sort an iterable by the clause number produced by ``key``."""
    return sorted(items, key=lambda item: clause_sort_key(key(item)))
