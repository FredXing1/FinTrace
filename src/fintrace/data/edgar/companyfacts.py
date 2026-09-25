"""Ingest SEC EDGAR ``companyfacts.zip`` into the PIT ``facts`` table.

Source: https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
One JSON per CIK with all as-filed XBRL facts since 2009; every fact carries the
``filed`` date, which is what makes point-in-time reconstruction possible.

NOTE: the ``frames`` API is intentionally NOT used anywhere in FinTrace — its
"closest period" matching can return facts that were amended after the frame
date, which is silent look-ahead.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any, cast

import duckdb
import pyarrow as pa

from fintrace.data.store import ensure_empty

COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
COMPANYFACTS_API = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"

_BATCH = 500_000  # rows per arrow flush
_FACT_COLUMNS = (
    "cik",
    "entity_name",
    "taxonomy",
    "tag",
    "unit",
    "period_start",
    "period_end",
    "val",
    "accn",
    "fy",
    "fp",
    "form",
    "filed",
    "frame",
)


def _int_or_none(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    return None


def _float_or_none(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_rows(doc: dict[str, Any], cols: dict[str, list[Any]]) -> None:
    """Append every fact of one companyfacts JSON (bulk-zip entry or per-CIK API
    response — same schema) into column buffers."""
    try:
        cik = int(doc["cik"])
    except (KeyError, TypeError, ValueError):
        return
    name = doc.get("entityName")
    for taxonomy, tags in (doc.get("facts") or {}).items():
        for tag, meta in tags.items():
            for unit, items in (meta.get("units") or {}).items():
                for f in items:
                    end = f.get("end")
                    val = _float_or_none(f.get("val"))
                    if not end or val is None:
                        continue
                    cols["cik"].append(cik)
                    cols["entity_name"].append(name)
                    cols["taxonomy"].append(taxonomy)
                    cols["tag"].append(tag)
                    cols["unit"].append(unit)
                    cols["period_start"].append(f.get("start"))
                    cols["period_end"].append(end)
                    cols["val"].append(val)
                    cols["accn"].append(f.get("accn"))
                    cols["fy"].append(_int_or_none(f.get("fy")))
                    cols["fp"].append(f.get("fp"))
                    cols["form"].append(f.get("form"))
                    cols["filed"].append(f.get("filed"))
                    cols["frame"].append(f.get("frame"))


def _flush(con: duckdb.DuckDBPyConnection, cols: dict[str, list[Any]]) -> int:
    if not cols["cik"]:
        return 0
    tbl = pa.Table.from_pydict(
        {
            "cik": pa.array(cols["cik"], pa.int64()),
            "entity_name": pa.array(cols["entity_name"], pa.string()),
            "taxonomy": pa.array(cols["taxonomy"], pa.string()),
            "tag": pa.array(cols["tag"], pa.string()),
            "unit": pa.array(cols["unit"], pa.string()),
            "period_start": pa.array(cols["period_start"], pa.string()),
            "period_end": pa.array(cols["period_end"], pa.string()),
            "val": pa.array(cols["val"], pa.float64()),
            "accn": pa.array(cols["accn"], pa.string()),
            "fy": pa.array(cols["fy"], pa.int64()),
            "fp": pa.array(cols["fp"], pa.string()),
            "form": pa.array(cols["form"], pa.string()),
            "filed": pa.array(cols["filed"], pa.string()),
            "frame": pa.array(cols["frame"], pa.string()),
        }
    )
    con.register("facts_batch", tbl)
    con.execute(
        """
        INSERT INTO facts
        SELECT cik, entity_name, taxonomy, tag, unit,
               TRY_CAST(period_start AS DATE), TRY_CAST(period_end AS DATE),
               val, accn, fy, fp, form,
               TRY_CAST(filed AS DATE), frame
        FROM facts_batch
        """
    )
    con.unregister("facts_batch")
    n = len(cols["cik"])
    for c in _FACT_COLUMNS:
        cols[c] = []
    return n


def ingest_doc(
    doc: dict[str, Any],
    con: duckdb.DuckDBPyConnection,
    *,
    append: bool = True,
) -> int:
    """Ingest one per-CIK companyfacts JSON (the data.sec.gov API response).

    Appends by default: incremental per-CIK pulls are the dev/smoke path. Rows
    may later overlap a bulk backfill — duplicate as-filed facts are identical
    rows and do not affect PIT queries (latest-filed ordering picks one)."""
    if not append:
        ensure_empty(con, "facts", append=False)
    cols: dict[str, list[Any]] = {c: [] for c in _FACT_COLUMNS}
    collect_rows(doc, cols)
    return _flush(con, cols)


def ingest(
    zip_path: str | Path,
    con: duckdb.DuckDBPyConnection,
    *,
    limit: int | None = None,
    append: bool = False,
) -> dict[str, int]:
    """Ingest companyfacts.zip. ``limit`` caps CIK files (smoke runs)."""
    ensure_empty(con, "facts", append=append)
    cols: dict[str, list[Any]] = {c: [] for c in _FACT_COLUMNS}
    n_files = n_facts = 0

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not info.filename.endswith(".json"):
                continue
            if limit is not None and n_files >= limit:
                break
            doc = cast("dict[str, Any]", json.loads(zf.read(info)))
            collect_rows(doc, cols)
            n_files += 1
            if n_files % 2000 == 0:
                print(f"[companyfacts] files={n_files} facts={n_facts}", file=sys.stderr)
            if len(cols["cik"]) >= _BATCH:
                n_facts += _flush(con, cols)
    n_facts += _flush(con, cols)
    return {"files": n_files, "facts": n_facts}
