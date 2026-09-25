"""Extract verifiable numeric claims from an answer text.

v0.1 scope: pattern-based extraction of numbers as written by humans —
``$394,328,000,000``, ``394.3 billion``, ``8.2M``, ``7.8%`` — plus noise
filters for years and accession-number fragments. The LLM-facing verifier
(P1-2) consumes these claims and binds them to PIT evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_PERCENT = re.compile(r"(?<![\w.\-])(\d[\d,]*(?:\.\d+)?)\s*%")

_NUMBER = re.compile(
    # Trailing lookahead allows '.' so sentence-final periods don't break the
    # match, but still rejects hyphenated fragments (10-K, 2022-10-28, accns).
    r"(?<![\w.\-])\$?(\d[\d,]*(?:\.\d+)?)\s*(trillion|billion|million|thousand|[KMBT])?(?![\w\-])",
    re.IGNORECASE,
)

_SCALES = {
    "trillion": 1e12,
    "billion": 1e9,
    "million": 1e6,
    "thousand": 1e3,
    "t": 1e12,
    "b": 1e9,
    "m": 1e6,
    "k": 1e3,
}


@dataclass(frozen=True)
class Claim:
    text: str  # the sentence containing the claim
    value: float  # scaled value (percents keep their % number, e.g. 7.8)
    is_percent: bool
    start: int  # character offset of the number inside the answer


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _scale_for(suffix: str | None) -> float:
    if not suffix:
        return 1.0
    return _SCALES[suffix.lower()]


def extract_claims(text: str) -> list[Claim]:
    """All verifiable numeric claims in ``text``, in order of appearance."""
    claims: list[Claim] = []
    offset = 0
    for sentence in _SENTENCE_SPLIT.split(text):
        _extract_from_sentence(sentence, offset, claims)
        offset += len(sentence) + 1
    return claims


def _extract_from_sentence(sentence: str, offset: int, claims: list[Claim]) -> None:
    consumed: list[tuple[int, int]] = []

    for match in _PERCENT.finditer(sentence):
        value = _to_float(match.group(1))
        claims.append(
            Claim(
                text=sentence.strip(),
                value=value,
                is_percent=True,
                start=offset + match.start(1),
            )
        )
        consumed.append(match.span())

    def in_consumed(start: int, end: int) -> bool:
        return any(cs <= start < ce or cs < end <= ce for cs, ce in consumed)

    for match in _NUMBER.finditer(sentence):
        if in_consumed(*match.span()):
            continue
        raw, suffix = match.group(1), match.group(2)
        value = _to_float(raw) * _scale_for(suffix)
        if suffix is None and value == int(value) and 1900 <= value <= 2100:
            continue  # bare year, not a financial claim
        if value == 0:
            continue
        claims.append(
            Claim(
                text=sentence.strip(),
                value=value,
                is_percent=False,
                start=offset + match.start(1),
            )
        )


def claims_to_dicts(claims: list[Claim]) -> list[dict[str, Any]]:
    return [
        {"text": c.text, "value": c.value, "is_percent": c.is_percent, "start": c.start}
        for c in claims
    ]
