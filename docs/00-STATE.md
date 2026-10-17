# Status

Last updated: 2026-10-17 | Phase: **v1.0 — project complete** | Next: none (maintenance only)

> Working notes for internal strategy/budget/session history are kept outside
> the public repository; this file tracks public-facing status only.

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
| bare model (GLM-4.7, thinking disabled) | 2/17 (**11.8%**) | 2% | 55.0% | 12.5% |

The naive pattern "wins" T3 by 30 points purely from look-ahead access — in a
naive backtest that is indistinguishable from forecasting alpha.

Replicated on a second model family (GLM-4.7, thinking disabled): **all 17
impossible questions answered with a specific value, 11.8% matching the true
future value** — identical to DeepSeek. The pattern is model-independent.

Full reports: `data/pitfall/report-deepseek-core200.json`,
`data/pitfall/leak-deepseek-core200.json` (generated locally by
`fintrace pitfall-run` / `fintrace pitfall-leak`).

Total LLM cost of both baseline runs: ≈ ¥4.4 (~$0.6).

## Roadmap

**Complete at v1.0.** Not carried forward (by scope decision, 2026-10-17):
promotional writing (blog, video, community/leaderboard operations), RQ4
return attribution (v1.x+). Maintenance only from here.

- [x] technical report v1.0 (`reports/technical-report.md`) — measurements,
      ablations, second-model replication, third-party audit, references
- [x] task pool 579; three-configuration leakage audit; TradingAgents
      v0.6.0 code-level PIT audit (`reports/tradingagents-audit.md`)
- [x] hosted demo: https://fintrace-demo.streamlit.app (zero-LLM
      time-travel playground; AppTest regression suite in CI)
- [x] ablation matrix (`fintrace pitfall-run --arm`,
      `scripts/ablation-local.sh`) on local open-weights models at zero API
      cost: T1-null leakage 0% (full gate) vs 35% (prompt only) vs 6%
      (gate only)
- [x] rolling walk-forward shadow evaluation (`fintrace pitfall-walkforward`)
- [x] dataset export with withheld T3 gold (`fintrace pitfall-export`;
      HF upload is a maintainer action with a personal token)
- [x] one-command deployment (`deploy/docker-compose.yml`: demo + docs +
      Prometheus metrics) and documentation site (`mkdocs.yml`)
- [x] monitoring: budget-ledger Prometheus exporter + Grafana dashboard
      (`deploy/grafana-dashboard.json`)

## Note on scope

Internal working documents (market research, project planning, budget) are
maintained outside this repository. This status file is the single public
source of truth for progress and results.
