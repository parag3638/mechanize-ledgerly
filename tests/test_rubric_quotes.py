"""Rubric evidence patterns (task/grader/rubric.py): quotes must name what the criterion is about."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "task"))

from grader.rubric import CRITERIA, quote_pattern

FACTS = {"dup_rows": 2, "dup_keys": 2}


def matches(cid: str, quote: str) -> bool:
    return re.search(quote_pattern(cid, FACTS), quote, re.IGNORECASE) is not None


def test_duplicate_count_as_digits_or_word() -> None:
    assert matches("C3_duplicate_count", "2 duplicate charges were created")
    assert matches(
        "C3_duplicate_count", "Two duplicate captures were refunded after on-call approval."
    )


def test_duplicate_count_rejects_other_numbers() -> None:
    assert not matches("C3_duplicate_count", "three duplicate charges were created")
    assert not matches("C3_duplicate_count", "12 duplicate charges were created")
    assert not matches("C3_duplicate_count", "twenty duplicate charges were created")


def test_every_criterion_has_a_pattern() -> None:
    for cid in CRITERIA:
        assert quote_pattern(cid, FACTS)
