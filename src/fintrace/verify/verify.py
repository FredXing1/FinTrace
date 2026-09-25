"""Bind answer claims to PIT evidence and verify them.

Verdicts per claim:
- ``supported``   — value matches evidence that was public at ``as_of``
- ``unsupported`` — no evidence in the run's tool results matches the value
- ``leaked``      — value matches evidence filed AFTER ``as_of``

``leaked`` is defense in depth: the tool layer already gates at ``as_of``, but
the verifier re-checks provenance independently, so a future non-gated source
cannot silently poison an answer.

Arithmetic verification recomputes stated growth percentages from the two most
recent distinct periods of the tag they bind to (e.g. "grew by 7.8%").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fintrace.verify.claims import Claim, extract_claims

_MATCH_REL_TOL = 0.005  # human text rounds; 0.5% relative tolerance
_GROWTH_PP_TOL = 0.15  # percentage-point tolerance for recomputed growth


@dataclass(frozen=True)
class Evidence:
    accn: str
    filed: str
    form: str | None
    cik: int | None
    entity: str | None
    tag: str
    period_start: str | None
    period_end: str
    value: float
    unit: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "accn": self.accn,
            "filed": self.filed,
            "form": self.form,
            "cik": self.cik,
            "entity": self.entity,
            "tag": self.tag,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
        }


def _as_day(value: Any) -> str:
    return str(value)[:10]


def _fact_to_evidence(fact: dict[str, Any], source: str) -> Evidence | None:
    if fact.get("val") is None or fact.get("accn") is None:
        return None
    return Evidence(
        accn=str(fact["accn"]),
        filed=_as_day(fact.get("filed")),
        form=fact.get("form"),
        cik=fact.get("cik"),
        entity=fact.get("entity_name"),
        tag=str(fact.get("tag")),
        period_start=_as_day(fact["period_start"]) if fact.get("period_start") else None,
        period_end=_as_day(fact.get("period_end")),
        value=float(fact["val"]),
        unit=str(fact.get("unit") or ""),
        source=source,
    )


def collect_evidence(trace_steps: list[dict[str, Any]]) -> list[Evidence]:
    """All PIT facts the run surfaced via tools, deduplicated."""
    evidence: list[Evidence] = []
    seen: set[tuple[str, str, str, float]] = set()
    for step in trace_steps:
        if step.get("type") != "tool" or not step.get("result", {}).get("ok"):
            continue
        name = str(step.get("name"))
        if name not in {"query_fact", "fact_history"}:
            continue
        result = step["result"].get("result")
        facts: list[dict[str, Any]] = []
        if isinstance(result, dict):
            facts = [result]
        elif isinstance(result, list):
            facts = [f for f in result if isinstance(f, dict)]
        for fact in facts:
            ev = _fact_to_evidence(fact, source=f"trace:{name}")
            if ev is None:
                continue
            dedup_key = (ev.accn, ev.tag, ev.period_end, ev.value)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            evidence.append(ev)
    return evidence


def _rel_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1.0)


def verify(
    answer: str | None, trace_steps: list[dict[str, Any]], as_of: str
) -> dict[str, Any]:
    claims = extract_claims(answer or "")
    evidence = collect_evidence(trace_steps)
    day = _as_day(as_of)
    time_gated_ok = all(ev.filed <= day for ev in evidence)

    verdicts: list[dict[str, Any]] = []
    bound: list[tuple[Claim, Evidence]] = []
    for claim in claims:
        matches = sorted(
            (ev for ev in evidence if _rel_diff(claim.value, ev.value) <= _MATCH_REL_TOL),
            key=lambda ev: _rel_diff(claim.value, ev.value),
        )
        if not matches:
            verdicts.append(
                {
                    "claim": claim.text,
                    "value": claim.value,
                    "is_percent": claim.is_percent,
                    "verdict": "unsupported",
                    "evidence": None,
                }
            )
            continue
        best = matches[0]
        verdict = "leaked" if best.filed > day else "supported"
        if not claim.is_percent:
            bound.append((claim, best))
        verdicts.append(
            {
                "claim": claim.text,
                "value": claim.value,
                "is_percent": claim.is_percent,
                "verdict": verdict,
                "evidence": best.to_dict(),
            }
        )

    arithmetic = _check_growth(
        [c for c in claims if c.is_percent], bound, evidence
    )

    summary = {
        "n_claims": len(claims),
        "supported": sum(v["verdict"] == "supported" for v in verdicts),
        "unsupported": sum(v["verdict"] == "unsupported" for v in verdicts),
        "leaked": sum(v["verdict"] == "leaked" for v in verdicts),
        "arithmetic_ok": all(a["ok"] for a in arithmetic if a["status"] == "checked"),
        "time_gated_ok": time_gated_ok,
    }
    return {
        "claims": verdicts,
        "arithmetic": arithmetic,
        "summary": summary,
        "evidence": [e.to_dict() for e in evidence],
    }


def _check_growth(
    percent_claims: list[Claim],
    bound: list[tuple[Claim, Evidence]],
    evidence: list[Evidence],
) -> list[dict[str, Any]]:
    """Recompute stated growth percentages from the two most recent distinct
    period ends of the tags the run's bound value claims came from. The full
    evidence set is searched (not just bound values): the prior-year fact does
    not have to be restated in the answer for growth to be checkable."""
    if not percent_claims:
        return []
    anchored = {ev.tag for _, ev in bound}

    checks: list[dict[str, Any]] = []
    for claim in percent_claims:
        candidates: list[list[Evidence]] = []
        for tag in sorted(anchored):
            latest: dict[str, Evidence] = {}
            for ev in (e for e in evidence if e.tag == tag):
                cur = latest.get(ev.period_end)
                if cur is None or ev.filed >= cur.filed:
                    latest[ev.period_end] = ev  # restatement-aware: latest filed wins
            evs = sorted(latest.values(), key=lambda x: x.period_end)
            if len(evs) >= 2:
                candidates.append(evs)
        if not candidates:
            checks.append(
                {
                    "stated_pct": claim.value,
                    "status": "not_checkable",
                    "ok": False,
                    "note": "no bound value pair to recompute from",
                }
            )
            continue
        evs = candidates[0]
        first, second = evs[-2], evs[-1]
        expected = round((second.value / first.value - 1) * 100, 4) if first.value else None
        ok = expected is not None and abs(claim.value - expected) <= _GROWTH_PP_TOL
        checks.append(
            {
                "stated_pct": claim.value,
                "status": "checked",
                "ok": ok,
                "expected_pct": expected,
                "tag": first.tag,
                "period_from": first.period_end,
                "period_to": second.period_end,
            }
        )
    return checks
