"""Task data model, JSONL I/O, and the core-set freeze manifest.

A task is a plain JSON-serializable dict (schema documented in the module for
the benchmark's public spec). Gold labels live inside the task file for v0.1
internal use; the public release must split gold into a separate file before
any leaderboard accepts submissions.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "0.1"


def task_to_dict(task: dict[str, Any]) -> dict[str, Any]:
    """Normalized field order for stable serialization."""
    return {
        "task_id": task["task_id"],
        "family": task["family"],
        "subtype": task["subtype"],
        "cik": task["cik"],
        "entity": task["entity"],
        "tag": task["tag"],
        "metric": task["metric"],
        "period_start": task["period_start"],
        "period_end": task["period_end"],
        "as_of": task["as_of"],
        "question": task["question"],
        "gold": task["gold"],
        "meta": task.get("meta", {}),
    }


def write_jsonl(tasks: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(task_to_dict(t), ensure_ascii=False, default=str) for t in tasks]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(dict(json.loads(line)))
    return out


def sha256_of_tasks(tasks: list[dict[str, Any]]) -> str:
    blob = "\n".join(json.dumps(task_to_dict(t), sort_keys=True, ensure_ascii=False) for t in tasks)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze_core(
    pool: list[dict[str, Any]],
    *,
    core_t1: int,
    core_t2: int,
    core_t3: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sample the frozen core subset. Same pool + seed -> same core, always."""
    rng = random.Random(seed ^ 0x5EED)
    core: list[dict[str, Any]] = []
    for family, n in (("T1", core_t1), ("T2", core_t2), ("T3", core_t3)):
        members = [t for t in pool if t["family"] == family]
        core.extend(rng.sample(members, min(n, len(members))))
    core.sort(key=lambda t: t["task_id"])
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seed": seed,
        "counts": {
            "pool": len(pool),
            "core": len(core),
            "core_by_family": {
                fam: sum(1 for t in core if t["family"] == fam) for fam in ("T1", "T2", "T3")
            },
        },
        "core_sha256": sha256_of_tasks(core),
        "note": "core-200 discipline: all self-run experiments only on this subset",
    }
    return core, manifest
