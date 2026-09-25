"""Data-directory resolution shared by CLI and library code."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    root = os.environ.get("FINTRACE_DATA_DIR")
    return Path(root) if root else Path("data")


def db_path() -> Path:
    return data_dir() / "fintrace.duckdb"


def raw_dir() -> Path:
    return data_dir() / "raw"


def traces_dir() -> Path:
    return data_dir() / "traces"


def ledger_path() -> Path:
    return data_dir() / "budget_ledger.sqlite"


def llm_cache_path() -> Path:
    return data_dir() / "llm_cache.sqlite"
