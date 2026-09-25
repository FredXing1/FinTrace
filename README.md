# FinTrace · PITfall

Auditable, point-in-time financial research agents & the PITfall leakage-controlled
benchmark — every claim traceable to as-filed evidence, zero look-ahead.

> ⚠️ Research software under active development. Not investment advice.

- 📍 **Status**: baselines complete — 125M as-filed facts, core-200 benchmark
  (T1 92% / T2 93.3% / T3 50%, bootstrap 95% CI), leakage audit showing a naive
  live-data agent answers 82% of "impossible" questions with the true future
  value. See [`docs/00-STATE.md`](docs/00-STATE.md).
- 💡 Total LLM cost of both full baseline runs: **≈ ¥4.4 (~$0.6)**.

## What's inside

| Module | Purpose |
|---|---|
| `fintrace-data` | Point-in-time EDGAR ingestion: as-filed XBRL facts gated by `filed` timestamps |
| `as_of(T)` | The PIT query primitive shared by runtime and benchmark — no default, no look-ahead |
| `pitfall-bench` | Leakage-controlled benchmark: time-gated QA, claim verification, forward estimation |
| `auditpack` | Open audit-trail schema: claims + evidence chains + execution logs + sign-off |

## Quick start (human developers)

```bash
make onboard   # environment check + onboarding reading order
make setup     # install toolchain
make check     # ruff + mypy + pytest
uv run fintrace query-fact --ticker AAPL --tag Revenues --period-end 2022-09-24 --as-of 2023-01-01
```

Every query takes a mandatory `as_of` date by design: asking "what was knowable
at T" is the core contract of this library.

## License

Apache-2.0


