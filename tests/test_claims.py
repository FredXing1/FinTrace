from __future__ import annotations

import pytest

from fintrace.verify.claims import extract_claims


def test_dollar_commas_and_percent() -> None:
    text = "Apple's FY2022 revenue was $394,328,000,000 (10-K filed 2022-10-28). It grew by 7.8%."
    claims = extract_claims(text)
    values = [c.value for c in claims]
    assert 394328000000.0 in values
    assert 7.8 in values
    percents = [c for c in claims if c.is_percent]
    assert len(percents) == 1 and percents[0].value == 7.8


def test_billion_and_suffix_notation() -> None:
    assert extract_claims("Revenue reached 394.3 billion.")[0].value == 394.3e9
    assert extract_claims("Revenue reached $394.3B.")[0].value == pytest.approx(394.3e9)
    assert extract_claims("Costs fell 8.2M.")[0].value == pytest.approx(8.2e6)


def test_years_and_accession_fragments_are_not_claims() -> None:
    text = "In 2022 the 10-K (accn 0000320193-22-000108) was filed 2022-10-28."
    assert [c.value for c in extract_claims(text)] == []


def test_empty_text() -> None:
    assert extract_claims("") == []
    assert extract_claims("No numbers here.") == []
