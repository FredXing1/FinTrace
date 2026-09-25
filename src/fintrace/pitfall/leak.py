"""Ungated baseline for leakage auditing (P2c).

Asks the bare model the same core-200 questions WITHOUT the as-of framing,
without tools, and without the "unknown" escape hatch. A naive backtest does
exactly this and scores the output — so any correct answer to a T1-null task
(whose true value was NOT public at as_of) is look-ahead leakage from training
memory, and any T3 "estimate" that lands on the realized number is memorization,
not forecasting.

The gated run (pitfall-run) vs this ungated run is the leakage audit delta.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from fintrace.core.llm import LLM
from fintrace.data.pit import PitStore
from fintrace.pitfall.scoring import score_task
from fintrace.verify.claims import extract_claims

_LEAK_REL_TOL = 0.01


def ungated_question(task: dict[str, Any]) -> str:
    """Strip the as-of framing from a gated question, keeping the identifier
    and the substance. Templates are known, so this is exact string surgery."""
    q = str(task["question"])
    family = task["family"]
    if family == "T1":
        q = q.replace("According to public SEC filings available as of", "As of")
        q = re.sub(r"As of (\d{4}-\d{2}-\d{2}), what was", r"What was", q)
        q = re.sub(
            r"\s*If this was not public at that date, answer exactly: unknown\.", "", q
        )
    elif family == "T2":
        q = re.sub(
            r"^As of \d{4}-\d{2}-\d{2}, is this statement correct according to public SEC "
            r"filings\? Answer with exactly 'true' or 'false', then cite the filing "
            r"\(accession number\)\. Statement: ",
            "Is the following statement correct? "
            "Answer with exactly 'true' or 'false'. Statement: ",
            q,
        )
    elif family == "T3":
        q = re.sub(r"^As of \d{4}-\d{2}-\d{2}, estimate", "What was", q)
        q = q.replace(
            ", using only information that was public at that time. Reply with a single "
            "number in USD.",
            "? Answer with a single number in USD.",
        )
    return q


def _leak_check(task: dict[str, Any], answer: str, store: PitStore) -> dict[str, Any] | None:
    """For T1-null tasks only: did the ungated model produce the realized
    (future) value? Returns None for other families."""
    if task["family"] != "T1" or task["gold"].get("kind") != "unknown":
        return None
    realized = store.fact(
        int(task["cik"]),
        str(task["tag"]),
        period_end=str(task["period_end"]),
        as_of="2200-01-01",
        period_start=task.get("period_start"),
    )
    realized_value = (
        float(realized["val"]) if realized and realized.get("val") is not None else None
    )
    claimed = [c.value for c in extract_claims(answer) if not c.is_percent]
    leak = any(
        realized_value is not None
        and abs(v - realized_value) / max(abs(realized_value), 1.0) <= _LEAK_REL_TOL
        for v in claimed
    )
    return {"realized_value": realized_value, "leak": leak}


def _run_one(
    task: dict[str, Any], llm: LLM, store: PitStore
) -> dict[str, Any]:
    question = ungated_question(task)
    try:
        resp = llm.complete([{"role": "user", "content": question}])
        answer = resp.content or ""
    except Exception as exc:  # noqa: BLE001 — transient provider errors are recorded, not fatal
        return {
            "task_id": task["task_id"],
            "family": task["family"],
            "subtype": task.get("subtype"),
            "question_ungated": question,
            "answer": None,
            "correct": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    outcome = score_task(task, answer)
    entry: dict[str, Any] = {
        "task_id": task["task_id"],
        "family": task["family"],
        "subtype": task.get("subtype"),
        "question_ungated": question,
        "answer": answer,
        **outcome,
    }
    leak_info = _leak_check(task, answer, store)
    if leak_info is not None:
        entry.update(leak_info)
    return entry


def run_leak_audit(
    tasks: list[dict[str, Any]],
    llm: LLM,
    store: PitStore,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        entry = _run_one(task, llm, store)
        results.append(entry)
        print(
            f"[pitfall-leak] {idx + 1}/{len(tasks)} {task['task_id']} "
            f"correct={entry['correct']}",
            file=sys.stderr,
            flush=True,
        )

    # second pass: tasks that errored (rate limits / transient load) get one
    # more attempt before the report is finalized
    failed_idx = [i for i, r in enumerate(results) if r.get("error")]
    if failed_idx:
        print(
            f"[pitfall-leak] retrying {len(failed_idx)} errored tasks",
            file=sys.stderr,
            flush=True,
        )
        for i in failed_idx:
            results[i] = _run_one(tasks[i], llm, store)

    by_family: dict[str, Any] = {}
    for family in ("T1", "T2", "T3"):
        family_results = [r for r in results if r["family"] == family]
        if not family_results:
            continue
        by_family[family] = {
            "n": len(family_results),
            "accuracy": sum(1.0 for r in family_results if r["correct"]) / len(family_results),
        }

    nulls = [r for r in results if r.get("gold_kind") == "unknown"]
    null_summary: dict[str, Any] | None = None
    if nulls:
        answered = [r for r in nulls if not r["correct"]]
        leaked = [r for r in nulls if r.get("leak")]
        null_summary = {
            "n_null_tasks": len(nulls),
            "ungated_said_unknown": len(nulls) - len(answered),
            "ungated_answered_a_value": len(answered),
            "leaked_true_value": len(leaked),
            "leakage_rate": len(leaked) / len(nulls),
            "examples": [
                {"task_id": r["task_id"], "answer": (r["answer"] or "")[:200]}
                for r in leaked[:5]
            ],
        }

    return {
        "n_tasks": len(tasks),
        "by_family": by_family,
        "t1_null_leak_audit": null_summary,
        "results": results,
    }
