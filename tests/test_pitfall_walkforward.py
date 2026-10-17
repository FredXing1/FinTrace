from __future__ import annotations

import json
from typing import Any

from fintrace.core.llm import LLMResponse, MockLLM
from fintrace.pitfall.walkforward import bucket_by_window, run_walkforward, subsample


def _t1(task_id: str, as_of: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "family": "T1",
        "subtype": "positive",
        "as_of": as_of,
        "question": "q",
        "gold": {"kind": "value", "value": 100.0},
    }


def test_bucket_by_window_half_open_and_gaps() -> None:
    tasks = [
        _t1("a", "2017-01-05"),
        _t1("b", "2017-12-31"),
        _t1("c", "2018-01-01"),  # next window
        _t1("d", "2019-06-01"),  # outside cover -> dropped
    ]
    buckets = bucket_by_window(tasks, "2017-01-01", "2019-01-01", 365)
    assert [label for label, _ in buckets] == ["2017-01-01", "2018-01-01"]
    assert [t["task_id"] for t in buckets[0][1]] == ["a", "b"]
    assert [t["task_id"] for t in buckets[1][1]] == ["c"]


def test_subsample_stride_keeps_coverage() -> None:
    tasks = [_t1(f"t{i}", "2017-01-01") for i in range(10)]
    assert len(subsample(tasks, 3)) == 3
    assert subsample(tasks, None) is tasks
    assert len(subsample(tasks[:2], 5)) == 2


def test_run_walkforward_reports_per_window() -> None:
    llm = MockLLM(
        [
            LLMResponse(content="100", tool_calls=[]),
            LLMResponse(content="unknown", tool_calls=[]),
        ]
    )
    tasks = [_t1("a", "2017-01-05"), _t1("b", "2018-06-01")]
    report = run_walkforward(
        tasks,
        lambda _t: llm.complete([]).content,
        start="2017-01-01",
        end="2019-01-01",
        step_days=365,
    )
    assert report["n_windows"] == 2
    assert report["n_windows_with_tasks"] == 2
    assert report["n_tasks_total"] == 2
    assert report["windows"][0]["by_family"]["T1"]["accuracy"] == 1.0
    assert report["windows"][1]["by_family"]["T1"]["accuracy"] == 0.0
    assert report["windows"][0]["t1_null_leak_audit"] is None


def test_export_withholds_t3_gold(tmp_path) -> None:
    from fintrace.cli import main

    def task(task_id: str, family: str, gold: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "family": family,
            "subtype": "x",
            "cik": 320193,
            "entity": "APPLE INC",
            "tag": "Revenues",
            "metric": "revenue",
            "period_start": None,
            "period_end": "2022-09-24",
            "as_of": "2022-01-01",
            "question": "q",
            "gold": gold,
            "meta": {},
        }

    pool = [
        task("t1-1", "T1", {"kind": "value", "value": 5.0}),
        task("t3-1", "T3", {"kind": "forward", "value": 9.0}),
    ]
    for name, tasks in (("pool", pool), ("core", pool)):
        (tmp_path / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(t) for t in tasks), encoding="utf-8"
        )
    (tmp_path / "manifest.json").write_text(json.dumps({"seed": 7}), encoding="utf-8")

    rc = main(
        [
            "pitfall-export",
            "--pool", str(tmp_path / "pool.jsonl"),
            "--core", str(tmp_path / "core.jsonl"),
            "--manifest", str(tmp_path / "manifest.json"),
            "--out", str(tmp_path / "dist"),
        ]
    )
    assert rc == 0
    exported = [
        json.loads(line) for line in (tmp_path / "dist" / "pool.jsonl").read_text().splitlines()
    ]
    by_id = {t["task_id"]: t for t in exported}
    assert by_id["t1-1"]["gold"] == {"kind": "value", "value": 5.0}  # intact
    assert by_id["t3-1"]["gold"] == {"kind": "forward", "gold_withheld": True}
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    assert manifest["seed"] == 7 and "gold_withheld" in manifest
