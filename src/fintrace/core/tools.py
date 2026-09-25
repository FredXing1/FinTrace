"""Tool protocol and the point-in-time tool set.

Every tool is a thin, JSON-serializable wrapper over a PIT-gated PitStore query.
``as_of`` is a REQUIRED argument in every schema — the runtime contract that no
call can silently read "today's" knowledge.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fintrace.data.pit import PitStore


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    fn: Callable[[dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _require_cik_and_as_of(args: dict[str, Any], store: PitStore) -> tuple[int, str]:
    as_of = args.get("as_of")
    if not as_of:
        raise ValueError("as_of is REQUIRED: every query is point-in-time gated")
    cik = args.get("cik")
    if cik is None:
        ticker = args.get("ticker")
        if not ticker:
            raise ValueError("provide either --cik or ticker")
        resolved = store.resolve_cik(str(ticker))
        if resolved is None:
            raise ValueError(f"unknown ticker: {ticker}")
        cik = resolved
    return int(cik), str(as_of)


def pit_tools(store: PitStore) -> list[Tool]:
    """The P0 tool set: fact lookup, filing index, as-known-at series."""

    def query_fact(args: dict[str, Any]) -> Any:
        cik, as_of = _require_cik_and_as_of(args, store)
        return store.fact(
            cik,
            str(args["tag"]),
            period_end=str(args["period_end"]),
            as_of=as_of,
            taxonomy=str(args.get("taxonomy") or "us-gaap"),
            unit=str(args.get("unit") or "USD"),
            period_start=args.get("period_start"),
        )

    def fact_history(args: dict[str, Any]) -> Any:
        cik, as_of = _require_cik_and_as_of(args, store)
        return store.history(
            cik,
            str(args["tag"]),
            as_of=as_of,
            taxonomy=str(args.get("taxonomy") or "us-gaap"),
            unit=str(args.get("unit") or "USD"),
        )

    def filing_history(args: dict[str, Any]) -> Any:
        cik, as_of = _require_cik_and_as_of(args, store)
        forms = args.get("forms")
        return store.filings(
            cik,
            as_of=as_of,
            forms=[str(f) for f in forms] if forms else None,
            limit=int(args.get("limit") or 20),
        )

    return [
        Tool(
            name="query_fact",
            description=(
                "Point-in-time value of one XBRL tag for one reporting period, "
                "as knowable at as_of. Returns null if not yet public at as_of."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "e.g. Revenues"},
                    "period_end": {"type": "string", "description": "YYYY-MM-DD"},
                    "as_of": {"type": "string", "description": "knowledge cutoff YYYY-MM-DD"},
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "period_start": {"type": "string"},
                    "taxonomy": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["tag", "period_end", "as_of"],
            },
            fn=query_fact,
        ),
        Tool(
            name="fact_history",
            description=(
                "As-known-at series of one XBRL tag (one row per period, latest filed <= as_of)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "as_of": {"type": "string"},
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "taxonomy": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["tag", "as_of"],
            },
            fn=fact_history,
        ),
        Tool(
            name="filing_history",
            description="Filing index (form, dates, accession numbers) visible at as_of.",
            parameters={
                "type": "object",
                "properties": {
                    "as_of": {"type": "string"},
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "forms": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": ["as_of"],
            },
            fn=filing_history,
        ),
    ]


_LATEST_AS_OF = "2200-01-01"  # sentinel: "as known today" for ungated tools


def pit_tools_ungated(store: PitStore) -> list[Tool]:
    """Naive-agent tool set: same shapes as the PIT tools but every query
    resolves to the LATEST known value regardless of any as-of argument.

    This is the dominant pattern in open-source finance agents — wire live
    APIs (yfinance, latest filings) without time gating. It exists so the
    leak audit can measure that pattern against the gated one.
    """

    def query_fact(args: dict[str, Any]) -> Any:
        cik = args.get("cik")
        if cik is None:
            resolved = store.resolve_cik(str(args.get("ticker")))
            if resolved is None:
                raise ValueError(f"unknown ticker: {args.get('ticker')}")
            cik = resolved
        return store.fact(
            int(cik),
            str(args["tag"]),
            period_end=str(args["period_end"]),
            as_of=_LATEST_AS_OF,
            taxonomy=str(args.get("taxonomy") or "us-gaap"),
            unit=str(args.get("unit") or "USD"),
            period_start=args.get("period_start"),
        )

    def filing_history(args: dict[str, Any]) -> Any:
        cik = args.get("cik")
        if cik is None:
            resolved = store.resolve_cik(str(args.get("ticker")))
            if resolved is None:
                raise ValueError(f"unknown ticker: {args.get('ticker')}")
            cik = resolved
        forms = args.get("forms")
        return store.filings(
            int(cik),
            forms=[str(f) for f in forms] if forms else None,
            limit=int(args.get("limit") or 20),
        )

    def fact_history(args: dict[str, Any]) -> Any:
        cik = args.get("cik")
        if cik is None:
            resolved = store.resolve_cik(str(args.get("ticker")))
            if resolved is None:
                raise ValueError(f"unknown ticker: {args.get('ticker')}")
            cik = resolved
        return store.history(
            int(cik),
            str(args["tag"]),
            as_of=_LATEST_AS_OF,
            taxonomy=str(args.get("taxonomy") or "us-gaap"),
            unit=str(args.get("unit") or "USD"),
        )

    return [
        Tool(
            name="query_fact",
            description=(
                "Latest reported value of one XBRL tag for a reporting period "
                "(most recent filing on record)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "e.g. Revenues"},
                    "period_end": {"type": "string", "description": "YYYY-MM-DD"},
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "period_start": {"type": "string"},
                    "taxonomy": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["tag", "period_end"],
            },
            fn=query_fact,
        ),
        Tool(
            name="fact_history",
            description="Full as-filed series of one XBRL tag (all periods on record).",
            parameters={
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "taxonomy": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["tag"],
            },
            fn=fact_history,
        ),
        Tool(
            name="filing_history",
            description="Filing index (form, dates, accession numbers), most recent first.",
            parameters={
                "type": "object",
                "properties": {
                    "cik": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "forms": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
            fn=filing_history,
        ),
    ]


class ToolBox:
    """Executes tools by name; wraps every result (or error) as a JSON dict."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            result = tool.fn(arguments)
            return {"ok": True, "tool": name, "result": result}
        except Exception as exc:  # noqa: BLE001 — tool errors must reach the LLM, not crash the loop
            return {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def dumps(result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, default=str)
