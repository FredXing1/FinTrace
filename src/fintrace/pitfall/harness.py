"""Minimal PITfall runner: execute tasks through an agent, score, aggregate.

The caller supplies ``run_fn(task) -> answer`` so the harness stays decoupled
from any particular LLM provider; report includes per-family accuracy with
bootstrap CIs and (when the caller tracks it) cost.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from fintrace.pitfall.scoring import bootstrap_ci, score_task


def run_tasks(
    tasks: list[dict[str, Any]],
    run_fn: Callable[[dict[str, Any]], str | None],
    *,
    ci_seed: int = 0,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        answer = run_fn(task)
        outcome = score_task(task, answer)
        results.append(
            {
                "task_id": task["task_id"],
                "family": task["family"],
                "subtype": task.get("subtype"),
                "answer": answer,
                **outcome,
            }
        )
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

    return {
        "n_tasks": len(tasks),
        "by_family": by_family,
        "results": results,
    }
