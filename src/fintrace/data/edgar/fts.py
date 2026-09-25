"""EDGAR full-text search (2001+) and primary-document fetch.

Search API: https://efts.sec.gov/LATEST/search-index (JSON; coverage since 2001;
rate limit <= 10 req/s). Documents live under https://www.sec.gov/Archives/edgar/data/.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from fintrace.data.http import SecHttpClient

FTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"


class JsonClient(Protocol):
    """Minimal client surface used by FTS functions (SecHttpClient satisfies it)."""

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


def search(
    client: JsonClient,
    query: str,
    *,
    forms: list[str] | None = None,
    startdt: str | None = None,
    enddt: str | None = None,
    start: int = 0,
    count: int = 50,
) -> dict[str, Any]:
    """One page of EDGAR FTS results (raw JSON payload)."""
    params: dict[str, Any] = {"q": query, "start": start, "count": min(count, 100)}
    if forms:
        params["forms"] = ",".join(forms)
    if startdt:
        params["dateRange"] = "custom"
        params["startdt"] = startdt
        params["enddt"] = enddt or startdt
    return client.get_json(FTS_URL, params=params)


def iter_hits(
    client: JsonClient,
    query: str,
    *,
    forms: list[str] | None = None,
    startdt: str | None = None,
    enddt: str | None = None,
    max_hits: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Page through search results, yielding hits until exhausted or ``max_hits``."""
    start = 0
    yielded = 0
    while True:
        payload = search(
            client,
            query,
            forms=forms,
            startdt=startdt,
            enddt=enddt,
            start=start,
            count=100,
        )
        hits = ((payload.get("hits") or {}).get("hits")) or []
        if not hits:
            return
        for hit in hits:
            yield hit
            yielded += 1
            if max_hits is not None and yielded >= max_hits:
                return
        start += len(hits)


def document_url(hit_id: str) -> str:
    """``{accession}:{filename}`` -> primary-document URL in the EDGAR archives."""
    accn, _, filename = hit_id.partition(":")
    if not accn or not filename:
        raise ValueError(f"unexpected EDGAR FTS _id format: {hit_id!r}")
    cik = int(accn.split("-")[0])
    return f"{ARCHIVES_URL}/{cik}/{accn.replace('-', '')}/{filename}"


def hit_id(hit: dict[str, Any]) -> str:
    source = hit.get("_source") or {}
    return str(hit.get("_id") or source.get("_id") or "")


def fetch_documents(
    client: SecHttpClient,
    hits: Iterator[dict[str, Any]] | list[dict[str, Any]],
    dest_dir: Path,
    limit: int = 5,
) -> list[Path]:
    """Download primary documents for up to ``limit`` hits into ``dest_dir/<accn>/``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for hit in hits:
        if len(out) >= limit:
            break
        hid = hit_id(hit)
        if not hid:
            continue
        accn, _, filename = hid.partition(":")
        out.append(client.download(document_url(hid), dest_dir / accn / filename))
    return out
