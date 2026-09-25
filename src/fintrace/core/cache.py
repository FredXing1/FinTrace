"""SQLite-backed LLM response cache (budget plan docs/03 §5).

Cache key = sha256 of the canonical JSON of (model, messages, tools, temperature).
Re-runs, paper replays and paper rewrites of the same run therefore cost ¥0.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fintrace.paths import llm_cache_path


def cache_key(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    temperature: float,
) -> str:
    canonical = json.dumps(
        {"model": model, "messages": messages, "tools": tools, "temperature": temperature},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path | str | None = None) -> None:
        target = str(path) if path is not None else str(llm_cache_path())
        if target != ":memory:":
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(target)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._con.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        value: dict[str, Any] = json.loads(row[0])
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO responses (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )
        self._con.commit()

    def close(self) -> None:
        self._con.close()
