"""Rolling walk-forward shadow evaluation (roadmap P3).

Slices a PITfall task file into consecutive as-of windows and runs each
window through the same harness, reporting per-window accuracy and T1-null
leakage. This is the monitoring posture: the benchmark re-scored as history
rolls forward, so drift in either dimension shows up as a trend across
windows instead of a single aggregate number.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fintrace.data.pit import PitStore
from fintrace.pitfall.harness import run_tasks


def bucket_by_window(
    tasks: list[dict[str, Any]],
    start: str,
    end: str,
    step_days: int,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group tasks into half-open ``[w, w + step)`` windows by their as_of.

    Tasks whose as_of falls outside ``[start, end)`` are dropped. Windows with
    no tasks are kept (empty), so the report shows the gap instead of hiding it.
    """
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    buckets: list[tuple[str, list[dict[str, Any]]]] = []
    window = start_d
    while window < end_d:
        next_window = window + timedelta(days=step_days)
        in_window = [
            t
            for t in tasks
            if window.isoformat() <= str(t["as_of"]) < next_window.isoformat()
        ]
        buckets.append((window.isoformat(), in_window))
        window = next_window
    return buckets


def subsample(tasks: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Deterministic stride sample, keeping coverage across the window."""
    if not limit or len(tasks) <= limit:
        return tasks
    stride = -(-len(tasks) // limit)  # ceil division
    return tasks[::stride][:limit]


def run_walkforward(
    tasks: list[dict[str, Any]],
    run_fn: Any,
    *,
    start: str,
    end: str,
    step_days: int,
    max_per_window: int | None = None,
    ci_seed: int = 0,
    store: PitStore | None = None,
) -> dict[str, Any]:
    """Run every window through ``run_tasks`` and nest the per-window reports."""
    windows: list[dict[str, Any]] = []
    for label, window_tasks in bucket_by_window(tasks, start, end, step_days):
        report = run_tasks(
            subsample(window_tasks, max_per_window),
            run_fn,
            ci_seed=ci_seed,
            store=store,
        )
        windows.append(
            {
                "window": label,
                "n_available": len(window_tasks),
                **report,
            }
        )
    scored = [w for w in windows if w["n_tasks"]]
    return {
        "start": start,
        "end": end,
        "step_days": step_days,
        "n_windows": len(windows),
        "n_windows_with_tasks": len(scored),
        "n_tasks_total": sum(w["n_tasks"] for w in windows),
        "windows": windows,
    }
