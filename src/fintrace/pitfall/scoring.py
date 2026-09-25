"""Scoring functions and bootstrap confidence intervals for PITfall.

v0.1 scoring is deterministic pattern/numeric matching (no LLM judge). T1
accepts any claimed value within 1% relative of gold; null-gold tasks require
an explicit unknown-style answer. T3 scores mean absolute percentage error.
"""

from __future__ import annotations

import random
import re
from typing import Any

from fintrace.verify.claims import extract_claims

_UNKNOWN = re.compile(
    r"\b(unknown|not\s+(?:yet\s+)?(?:public|available|disclosed|released)"
    r"|no\s+(?:such\s+)?(?:data|information|filing|report)"
    r"|(?:do\s+not|don't|cannot|can't)\s+have"
    r"|unable)\b",
    re.IGNORECASE,
)
_TRUE = re.compile(r"\b(true|correct|accurate|yes)\b", re.IGNORECASE)
_FALSE = re.compile(r"\b(false|incorrect|inaccurate|wrong|no)\b", re.IGNORECASE)

_T1_REL_TOL = 0.01
_T3_PASS_APE = 0.20


def score_task(task: dict[str, Any], answer: str | None) -> dict[str, Any]:
    """Dispatch on family; returns {correct, ...family-specific detail}."""
    if not answer:
        return {"correct": False, "detail": "no answer"}
    family = task["family"]
    if family == "T1":
        return score_t1(task, answer)
    if family == "T2":
        return score_t2(task, answer)
    if family == "T3":
        return score_t3(task, answer)
    return {"correct": False, "detail": f"unknown family {family}"}


def score_t1(task: dict[str, Any], answer: str) -> dict[str, Any]:
    gold = task["gold"]
    if gold["kind"] == "unknown":
        says_unknown = bool(_UNKNOWN.search(answer))
        return {
            "correct": says_unknown,
            "gold_kind": "unknown",
            "detail": None if says_unknown else "answered something instead of unknown",
        }
    gold_value = float(gold["value"])
    values = [c.value for c in extract_claims(answer) if not c.is_percent]
    hit = any(abs(v - gold_value) / max(abs(gold_value), 1.0) <= _T1_REL_TOL for v in values)
    return {
        "correct": hit,
        "gold_kind": "value",
        "claimed_values": values[:5],
        "detail": None if hit else f"no claim within 1% of {gold_value}",
    }


def score_t2(task: dict[str, Any], answer: str) -> dict[str, Any]:
    expected = task["gold"]["kind"]  # "true" | "false"
    says_true = bool(_TRUE.search(answer))
    says_false = bool(_FALSE.search(answer))
    if says_true == says_false:  # both or neither -> ambiguous
        return {"correct": False, "gold_kind": expected, "detail": "ambiguous verdict"}
    stated = "true" if says_true else "false"
    return {
        "correct": stated == expected,
        "gold_kind": expected,
        "stated": stated,
        "cited_accn": bool(re.search(r"\d{10}-\d{2}-\d{6}", answer)),
    }


def score_t3(task: dict[str, Any], answer: str) -> dict[str, Any]:
    gold_value = task["gold"].get("value")
    if gold_value is None:
        return {"correct": False, "detail": "task has no gold value"}
    values = [c.value for c in extract_claims(answer) if not c.is_percent]
    if not values:
        return {"correct": False, "detail": "no numeric prediction found"}
    ape = min(abs(v - float(gold_value)) / abs(float(gold_value)) for v in values)
    return {
        "correct": ape <= _T3_PASS_APE,
        "ape": ape,
        "gold_value": float(gold_value),
        "detail": None,
    }


def bootstrap_ci(
    values: list[float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Percentile bootstrap CI for the mean. values are 0/1 flags (accuracy)
    or continuous scores (APE)."""
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0}
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_boot)
    )
    lo_idx = int(n_boot * alpha / 2)
    return {
        "mean": sum(values) / n,
        "low": means[lo_idx],
        "high": means[min(n_boot - 1, int(n_boot * (1 - alpha / 2)))],
    }
