"""Clause-number ordering (09 §7.1 test_clause_no_sorting). No DB needed."""

from common.sorting import clause_sort_key, sort_by_clause


def test_two_point_ten_sorts_after_two_point_two():
    """The case string sorting gets wrong.

    Lexicographically "2.10" < "2.2", which would put clause 2.10 between 2.1
    and 2.2 in every table and export.
    """
    assert sorted(["2.10", "2.2", "2.1"], key=clause_sort_key) == ["2.1", "2.2", "2.10"]
    assert "2.10" < "2.2"  # the naive comparison this guards against


def test_sample_clause_order():
    """All 17 sample clauses come out in document order."""
    shuffled = [
        "5.3", "2.10", "3.1", "2.2", "4.4", "2.1", "5.1", "3.10",
        "4.1", "2.5", "3.4", "5.4", "4.3", "2.3", "3.2", "2.4",
        "5.2", "4.2", "3.3",
    ]
    assert sorted(shuffled, key=clause_sort_key) == [
        "2.1", "2.2", "2.3", "2.4", "2.5", "2.10",
        "3.1", "3.2", "3.3", "3.4", "3.10",
        "4.1", "4.2", "4.3", "4.4",
        "5.1", "5.2", "5.3", "5.4",
    ]


def test_announcement_clauses_sort_after_spec_clauses():
    """``공고 3.3`` comes from the announcement, so it follows the spec sheet.

    specs/08-sample-data.md 1.3: it duplicates spec clause 5.4 in substance but
    both rows are kept, so their relative order must be stable.
    """
    assert sorted(["공고 3.3", "5.4", "2.1", "공고 3.1"], key=clause_sort_key) == [
        "2.1", "5.4", "공고 3.1", "공고 3.3",
    ]


def test_blank_and_missing_sort_last():
    assert sorted(["", "2.1", None, "부록"], key=clause_sort_key)[0] == "2.1"
    ordered = sorted(["2.1", "", "3.1"], key=clause_sort_key)
    assert ordered == ["2.1", "3.1", ""]


def test_single_and_deep_levels():
    assert sorted(["2", "2.1", "2.1.1", "10"], key=clause_sort_key) == [
        "2", "2.1", "2.1.1", "10",
    ]


def test_sort_by_clause_with_objects():
    rows = [{"clause_no": "2.10"}, {"clause_no": "2.2"}]
    assert [r["clause_no"] for r in sort_by_clause(rows, key=lambda r: r["clause_no"])] == [
        "2.2", "2.10",
    ]
