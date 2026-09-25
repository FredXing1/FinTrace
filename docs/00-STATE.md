# Status

Last updated: 2026-09-25 | Phase: benchmark + leakage audit complete | Next: public launch

## What exists today

- **Data layer** — 125,497,647 as-filed XBRL facts across 20,396 filers, every fact
  carrying its `filed` timestamp; all queries point-in-time gated at `as_of(T)`.
- **Agent runtime** — pluggable OpenAI-compatible providers, budget governor
  (pre-flight authorization + persistent spend ledger + hard cap), response cache,
  fully-traced ReAct loop.
- **Verification** — numeric-claim extraction → evidence binding →
  `supported` / `unsupported` / `leaked` verdicts → arithmetic recomputation →
  **auditpack v0.1** (open JSON Schema: conclusion + evidence chain + execution
  log + human sign-off).
- **PITfall benchmark** — three task families (time-gated QA incl. unknown-gold
  leakage probes, claim verification, forward estimation), pool of 579 tasks,
  frozen core-200 with sha256 manifest.

## First baseline (deepseek-chat agent, bootstrap 95% CI)

| family | n | accuracy |
|---|---|---|
| T1 time-gated QA | 100 | **92%** [86, 97] |
| T2 claim verification | 60 | **93.3%** [86.7, 98.3] |
| T3 forward estimation | 40 | **50%** [35, 65] |

T1 includes 17 "impossible" tasks whose answers were not public at the as_of
date: the gated agent answers "unknown" on 16/17 of them.

## Leakage audit (same core-200, ungated baselines)

| baseline | T1-null: answers the true future value | T1 acc | T2 acc | T3 acc |
|---|---|---|---|---|
| bare model (no tools, no as-of framing) | 2/17 (**11.8%**) | 5% | 53.3% | 25% |
| naive agent (live-data tools, no time gate) | **14/17 (82%)** | 77% | 86.7% | **80%** |
| gated FinTrace agent | **0/17 (says "unknown" 94%)** | **92%** | **93.3%** | 50% |

The naive pattern "wins" T3 by 30 points purely from look-ahead access — in a
naive backtest that is indistinguishable from forecasting alpha.

Full reports: `data/pitfall/report-deepseek-core200.json`,
`data/pitfall/leak-deepseek-core200.json` (generated locally by
`fintrace pitfall-run` / `fintrace pitfall-leak`).

Total LLM cost of both baseline runs: ≈ ¥4.4 (~$0.6).

## Roadmap

- [ ] expand task pool; audit third-party agent frameworks
- [ ] hosted demo + public dataset release
- [ ] technical report
