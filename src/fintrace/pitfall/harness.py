"""Minimal PITfall runner: execute tasks through an agent, score, aggregate.

The caller supplies ``run_fn(task) -> answer`` so the harness stays decoupled
from any particular LLM provider; report includes per-family accuracy with
bootstrap CIs, per-task latency, and (when a PitStore is supplied) the T1-null
leakage audit so ablation arms compare on the RQ1 metric.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from fintrace.data.pit import PitStore
from fintrace.pitfall.leak import leak_check
from fintrace.pitfall.scoring import bootstrap_ci, score_task


def run_tasks(
    tasks: list[dict[str, Any]],
    run_fn: Callable[[dict[str, Any]], str | None],
    *,
    ci_seed: int = 0,
    store: PitStore | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        started = time.monotonic()
        answer = run_fn(task)
        latency_s = time.monotonic() - started
        outcome = score_task(task, answer)
        entry: dict[str, Any] = {
            "task_id": task["task_id"],
            "family": task["family"],
            "subtype": task.get("subtype"),
            "answer": answer,
            "latency_s": round(latency_s, 3),
            **outcome,
        }
        if store is not None and answer:
            leak_info = leak_check(task, answer, store)
            if leak_info is not None:
                entry.update(leak_info)
        results.append(entry)
        print(
            f"[pitfall-run] {idx + 1}/{len(tasks)} {task['task_id']} "
            f"correct={outcome['correct']}",
            file=sys.stderr,
            flush=True,
        )

    by_family: dict[str, Any] = {}
    for family in ("T1", "T2", "T3"):
        family_results = [r for r in results if r["family"] == family]
        if not family_results:
            continue
        flags = [1.0 if r["correct"] else 0.0 for r in family_results]
        ci = bootstrap_ci(flags, seed=ci_seed)
        by_family[family] = {
            "n": len(family_results),
            "accuracy": ci["mean"],
            "accuracy_ci95": [ci["low"], ci["high"]],
        }

    t3_apes = [r["ape"] for r in results if r["family"] == "T3" and r.get("ape") is not None]
    if t3_apes:
        ape_ci = bootstrap_ci(t3_apes, seed=ci_seed)
        by_family["T3"]["mean_ape"] = ape_ci["mean"]
        by_family["T3"]["ape_ci95"] = [ape_ci["low"], ape_ci["high"]]

    nulls = [r for r in results if r.get("gold_kind") == "unknown"]
    null_summary: dict[str, Any] | None = None
    if nulls and store is not None:
        leaked = [r for r in nulls if r.get("leak")]
        null_summary = {
            "n_null_tasks": len(nulls),
            "answered_a_value": len(nulls) - sum(1 for r in nulls if r["correct"]),
            "leaked_true_value": len(leaked),
            "leakage_rate": len(leaked) / len(nulls),
        }

    return {
        "n_tasks": len(tasks),
        "by_family": by_family,
        "t1_null_leak_audit": null_summary,
        "results": results,
    }
