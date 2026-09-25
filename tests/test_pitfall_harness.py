from __future__ import annotations

from fintrace.pitfall.harness import run_tasks


def test_run_tasks_report() -> None:
    tasks = [
        {
            "task_id": "t1-1",
            "family": "T1",
            "subtype": "positive",
            "gold": {"kind": "value", "value": 100.0},
            "question": "q1",
        },
        {
            "task_id": "t2-1",
            "family": "T2",
            "subtype": "true",
            "gold": {"kind": "true"},
            "question": "q2",
        },
    ]
    report = run_tasks(tasks, lambda t: "100" if t["family"] == "T1" else "true", ci_seed=1)
    assert report["n_tasks"] == 2
    assert report["by_family"]["T1"]["accuracy"] == 1.0
    assert report["by_family"]["T2"]["accuracy"] == 1.0
    assert len(report["results"]) == 2
    assert report["results"][0]["correct"] is True


def test_run_tasks_handles_no_answer() -> None:
    tasks = [
        {
            "task_id": "t1-1",
            "family": "T1",
            "subtype": "positive",
            "gold": {"kind": "value", "value": 1.0},
        }
    ]
    report = run_tasks(tasks, lambda _t: None)
    assert report["results"][0]["correct"] is False
    assert report["by_family"]["T1"]["accuracy"] == 0.0
