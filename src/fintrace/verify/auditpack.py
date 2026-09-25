"""Build and persist auditpacks — the open, signable audit format.

An auditpack bundles everything a reviewer needs to reproduce and challenge a
run: the question and knowledge cutoff, the conclusion, per-claim verification
verdicts, the evidence chain (filing/accn/filed), the full execution log, and a
human sign-off block that ships unsigned until a reviewer signs it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fintrace.paths import traces_dir

AUDITPACK_VERSION = "0.1"


def load_schema() -> dict[str, Any]:
    """The bundled JSON Schema for the current auditpack version."""
    path = (
        Path(__file__).resolve().parent.parent / "schemas" / f"auditpack-v{AUDITPACK_VERSION}.json"
    )
    return dict(json.loads(path.read_text(encoding="utf-8")))


def build_auditpack(
    question: str,
    as_of: str,
    answer: str | None,
    trace_dict: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    return {
        "auditpack_version": AUDITPACK_VERSION,
        "run_id": str(trace_dict.get("run_id", "")),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "question": question,
        "as_of": str(as_of)[:10],
        "conclusion": {"answer": answer},
        "verification": verification,
        "evidence": list(verification.get("evidence", [])),
        "execution_log": list(trace_dict.get("steps", [])),
        "human_signoff": {"approved": False, "reviewer": None, "signed_at": None},
    }


def save_auditpack(pack: dict[str, Any], directory: Path | None = None) -> Path:
    out_dir = directory if directory is not None else traces_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{pack['run_id']}.auditpack.json"
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
