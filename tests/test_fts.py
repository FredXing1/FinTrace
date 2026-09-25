from __future__ import annotations

from typing import Any

import pytest

from fintrace.data.edgar import fts


def test_document_url() -> None:
    url = fts.document_url("0000320193-23-000106:aapl-20230930.htm")
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"


def test_document_url_rejects_bad_id() -> None:
    with pytest.raises(ValueError, match="_id"):
        fts.document_url("no-colon-here")


class FakeClient:
    """Satisfies fts.JsonClient; returns canned pages in order, one page per call."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        self.calls.append(params)
        page_no = len(self.calls) - 1
        page = self.pages[page_no] if page_no < len(self.pages) else []
        return {"hits": {"total": {"value": 99}, "hits": page}}


def _hit(i: int) -> dict[str, Any]:
    hid = f"0000320193-23-00010{i}:doc{i}.htm"
    return {"_id": hid, "_source": {"_id": hid, "file_date": "2023-11-03"}}


def test_iter_hits_pages_until_empty() -> None:
    client = FakeClient([[_hit(0), _hit(1)], [_hit(2)]])
    got = list(fts.iter_hits(client, "q"))
    assert len(got) == 3
    assert client.calls[0]["start"] == 0
    assert client.calls[1]["start"] == 2


def test_iter_hits_respects_max() -> None:
    client = FakeClient([[_hit(0), _hit(1)], [_hit(2)]])
    got = list(fts.iter_hits(client, "q", max_hits=2))
    assert len(got) == 2


def test_search_params() -> None:
    client = FakeClient([[_hit(0)]])
    fts.search(
        client,
        "risk",
        forms=["10-K", "10-Q"],
        startdt="2023-01-01",
        enddt="2023-06-30",
        count=100,
    )
    p = client.calls[0]
    assert p["forms"] == "10-K,10-Q"
    assert p["dateRange"] == "custom"
    assert p["startdt"] == "2023-01-01" and p["enddt"] == "2023-06-30"
    assert p["count"] == 100  # capped at 100
