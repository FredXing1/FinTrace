from __future__ import annotations

from typing import Any

import pytest

from fintrace.pitfall.scoring import bootstrap_ci, score_task


def _t1_value() -> dict[str, Any]:
    return {"task_id": "t1-1", "family": "T1", "gold": {"kind": "value", "value": 394328000000.0}}


def _t1_unknown() -> dict[str, Any]:
    return {"task_id": "t1-2", "family": "T1", "gold": {"kind": "unknown"}}


def test_t1_numeric_within_tolerance() -> None:
    task = _t1_value()
    assert score_task(task, "It was 394,300,000,000.")["correct"] is True
    assert score_task(task, "It was 350,000,000,000.")["correct"] is False


def test_t1_unknown_gold() -> None:
    task = _t1_unknown()
    assert score_task(task, "unknown — not public at that date.")["correct"] is True
    assert score_task(task, "It was 394.3 billion.")["correct"] is False


def test_t2_verdict_words() -> None:
    task = {"task_id": "t2-1", "family": "T2", "gold": {"kind": "true"}}
    assert score_task(task, "true. See accn 0000320193-22-000108.")["correct"] is True
    assert score_task(task, "false — the real figure differs.")["correct"] is False
    assert score_task(task, "maybe?")["correct"] is False  # ambiguous


def test_t3_ape() -> None:
    task = {
        "task_id": "t3-1",
        "family": "T3",
        "gold": {"kind": "forward", "value": 400_000_000_000.0},
    }
    near = score_task(task, "My estimate is 380,000,000,000.")  # APE 5%
    assert near["correct"] is True and near["ape"] == pytest.approx(0.05)
    far = score_task(task, "About 700,000,000,000.")  # APE 75%
    assert far["correct"] is False


def test_bootstrap_ci_basic() -> None:
    ci = bootstrap_ci([1.0, 1.0, 1.0, 0.0], n_boot=500, seed=1)
    assert ci["mean"] == pytest.approx(0.75)
    assert 0.0 <= ci["low"] <= ci["mean"] <= ci["high"] <= 1.0


def test_bootstrap_ci_empty() -> None:
    assert bootstrap_ci([]) == {"mean": 0.0, "low": 0.0, "high": 0.0}
