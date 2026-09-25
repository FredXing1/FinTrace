"""Execution trace: every step of an agent run, serialized to disk.

This is the seed of ``auditpack`` (formalized in P1-2): a run's conclusions must
be reconstructible from (question, as_of, every LLM call, every tool call, every
result). Saved under ``data/traces/<run_id>.json``.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fintrace.paths import traces_dir


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass
class RunTrace:
    question: str
    as_of: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(self, step: dict[str, Any]) -> None:
        self.steps.append(step)

    def finish(self) -> None:
        self.finished_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "as_of": self.as_of,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
        }

    def save(self, directory: Path | None = None) -> Path:
        out_dir = directory if directory is not None else traces_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.run_id}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path
