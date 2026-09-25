# FinTrace: Point-in-Time Guardrails and a Leakage-Controlled Benchmark for Financial LLM Agents

**Technical Report — v0.1 draft** · 2026-09 · Apache-2.0 · code at `github.com/FredXing1/FinTrace`

> Status: draft skeleton. Numbers in §5.2 and §5.3 are final measured results
> (deepseek-chat backbone). Entries marked **[TODO]** await ongoing runs
> (second-model replication, ablation matrix) and will be filled in the next
> revision.

---

## Abstract

LLM-based financial agents are increasingly evaluated — and increasingly
trusted — on historical market questions. Yet most such evaluations are
compromised by *look-ahead leakage*: the model's pretraining corpus contains
the filings that postdate the evaluation's reference date, and naive tooling
fetches "latest known" data that would not have been available at decision
time. We present **FinTrace**, an open-source framework that makes point-in-time
discipline *structural*: a data layer over SEC EDGAR in which every one of
125.5M as-filed XBRL facts carries its `filed` timestamp, a single mandatory
`as_of(T)` query primitive shared by runtime and benchmark, and an audit-trail
format (**auditpack**) that binds every numeric claim to its evidence.

We also present **PITfall**, a leakage-controlled benchmark generated
deterministically from EDGAR (pool of 579 tasks; frozen core-200 with sha256
manifest). PITfall includes *impossible* tasks — questions whose true answers
were not public at the reference date — where the only correct answer is
"unknown". On this benchmark, a gated agent (deepseek-chat backbone) scores
92% / 93.3% / 50% on time-gated QA, claim verification, and forward estimation
respectively, answers "unknown" on 16/17 impossible tasks, and leaks nothing.
Removing the time gate — asking the bare model the same questions — produces
the true future value on 2/17 impossible tasks directly from training memory;
wiring a naive agent to live-data tools (the dominant open-source pattern)
raises that to 14/17 (82%) and inflates forward "forecasting" accuracy from
50% to 80%. All three configurations cost under ¥5 (~$0.7) in total LLM fees,
and the entire pipeline is reproducible byte-for-byte from public EDGAR data.

---

## 1. Introduction

### 1.1 The evaluation crisis in financial LLM agents

[todo: expand — LLM trading agents report Sharpe ratios from backtests whose
information sets include the future; PAKDD'26 survey catalogues five
evaluation failures (look-ahead, survivorship, backtest overfitting, ignored
costs, regime blindness) that can flip return signs; Stanford/Vals FinanceAgent
shows best frontier model at 46.8% on expert tasks at $3.79/task]

### 1.2 Contributions

1. A PIT data layer over SEC EDGAR: 125.5M as-filed facts with `filed`-gated
   queries; per-CIK API paths; FTS crawling since 2001. **[§3.1]**
2. A mandatory-`as_of(T)` query primitive shared verbatim by the runtime and
   the benchmark — evaluation and deployment cannot diverge. **[§3.2]**
3. PITfall: a deterministic, seeded task generator with three families and
   built-in leakage controls (impossible/unknown-gold probes verified against
   *all* filing forms, 8-K pre-announcement filtering, restatement-aware
   gold). **[§4]**
4. A three-configuration leakage audit (bare model / naive live-data agent /
   gated agent) quantifying look-ahead inflation on identical tasks. **[§5.3]**
5. **auditpack v0.1**: an open JSON Schema for auditable agent output —
   conclusion, per-claim verdicts, evidence chain, execution log, human
   sign-off. **[§6]**
6. A cost-disciplined protocol: the full 200-task gated baseline plus a
   200-task ungated audit cost ≈ ¥4.4 (~$0.6) in LLM fees. **[§5.1]**

## 2. Background and Related Work

### 2.1 Look-ahead leakage and the Alpha Illusion

[todo: expand — Glasserman & Lin on ChatGPT sentiment backtests; Look-Ahead
Bench; KTD-Fin (returns explained by style exposure); "The Alpha Illusion"
P1–P6 reporting protocol; FinCAD in-context decoding correction]

### 2.2 Benchmarks and their gaps

[todo: expand — FinanceBench (static, small, no time dimension); FinBen /
PIXIU / FinEval (pre-agent NLP); InvestorBench; FinanceAgent (expert tasks,
no provenance axis); the 2025–26 wave of time-aware benchmarks and how
PITfall differs: unknown-gold probes verified against all filing forms +
structural gating shared with a deployable runtime]

## 3. The FinTrace Framework

### 3.1 Point-in-time data layer over SEC EDGAR

Sources, licensing (public domain), and volumes:

| source | content | volume | PIT anchor |
|---|---|---|---|
| XBRL company facts (bulk + per-CIK API) | as-filed financial facts since 2009 | 125,497,647 facts / 20,396 filers / 2.4 GB | `filed` timestamp |
| submissions (per-CIK API) | filing index | 1,000 filings (AAPL smoke) | `filing_date` |
| company_tickers.json | ticker ↔ CIK map | 8,049 entities | — |
| EDGAR full-text search | document retrieval since 2001 | on demand | `file_date` |

Engineering notes: the XBRL `frames` API is intentionally unused (its
"closest period" matching introduces silent look-ahead); evidence assembly is
set-based (temp-table joins) rather than per-candidate scans.

### 3.2 `as_of(T)`: one primitive, two consumers

[explain: runtime tools and benchmark gold share the same code path; `as_of`
is a *required* argument everywhere — no silent "today"; restatement rule =
latest `filed <= T` per period, `accn` as tiebreaker; worked example: Apple
FY2022 revenue as known on 2022-10-01 (unknown) / 2023-01-01 ($394,328M via
the original 10-K) / 2024-06-30 (restated value via the FY2023 10-K)]

### 3.3 Agent runtime

[pluggable OpenAI-compatible providers; budget governor with pre-flight
authorization, persistent ledger, hard cap; response cache keyed on
(model, messages, tools, temperature); traced ReAct loop — every LLM call and
tool call recorded]

### 3.4 Verification

[claim extraction (human-notation numbers), evidence binding at 0.5%
relative tolerance, verdicts supported/unsupported/leaked, growth-percentage
recomputation from the two most recent distinct periods]

## 4. The PITfall Benchmark

### 4.1 Task families

| family | question shape | gold | metric |
|---|---|---|---|
| T1 time-gated QA | "as of T, what was X's metric for period P?" | latest filed ≤ T value, or `unknown` | 1% relative tolerance |
| T2 claim verification | "is this statement correct?" (true / perturbed-false) | truth + evidence accn | verdict match + citation |
| T3 forward estimation | "as of T, estimate next-year X" | realized value, filed after T | APE (pass ≤ 20%) |

### 4.2 Leakage controls

[impossible-task construction: as_of = first disclosure − 1 day, candidate
dropped unless the set-based join confirms zero prior facts of ANY form —
filters 8-K pre-announcements; forward window anchored on first-filed dates
because last-filed is polluted by comparative restatements]

### 4.3 Generation and freezing

[deterministic, seeded; pool 579 → frozen core-200 (T1×100 incl. 17 null /
T2×60 / T3×40), sha256 manifest; T3 gold withheld at publish]

## 5. Experiments

### 5.1 Setup

[deepseek-chat backbone via OpenAI-compatible API, temperature 0, max 6
steps; 445 LLM calls / ¥3.04 (~$0.42) for the gated 200-task run; scoring
deterministic, no LLM judge; bootstrap CIs (2000 resamples)]

### 5.2 Gated baselines (frozen core-200)

| family | n | accuracy | 95% CI |
|---|---|---|---|
| T1 time-gated QA | 100 | **92%** | [86, 97] |
| — incl. 17 null-gold probes | 17 | **94%** (16/17 "unknown") | — |
| T2 claim verification | 60 | **93.3%** | [86.7, 98.3] |
| T3 forward estimation | 40 | **50%** | [35, 65] |

[T3 mean APE 136% — heavy tail; median substantially better; discussion of
small-cap long tail]

### 5.3 Leakage audit: gated vs ungated

| configuration | T1-null: answers true future value | T1 acc | T2 acc | T3 acc |
|---|---|---|---|---|
| bare model (no tools, no as-of framing) | 2/17 (**11.8%**) | 5% | 53.3% | 25% |
| naive agent (live-data tools, no gate) | **14/17 (82%)** | 77% | 86.7% | **80%** |
| gated FinTrace agent | **0/17** (94% say "unknown") | **92%** | **93.3%** | 50% |

[todo: per-task table for the 17 null probes, including the CNX Resources
hallucination case; discussion — the 30-point T3 swing is look-ahead access,
while T1-positive accuracy is flat (93% vs 92%), i.e. the naive agent is not
smarter, only unsound; two leaked null answers (Enable Midstream, Carvana)
would be scored as alpha in a naive backtest]

### 5.4 Ablations

**[TODO]** — planned ablation arms: −time-gate / −unknown-escape-hatch /
−tools (parametric only) / −claim-verification; each reported against
leakage rate, unsupported rate, accuracy, and cost.

### 5.5 Second-model replication

**[TODO]** — GLM-4.7 (thinking) and Kimi K2.6 runs in progress; reported
with identical protocol.

## 6. auditpack: an audit-trail schema

[schema walkthrough — required fields, verdict enums, sign-off block;
validation via JSON Schema draft 2020-12; intended consumers: compliance
reviewers, backtest authors, evaluation harnesses]

## 7. Limitations and Threats to Validity

- construct: unknown-gold probes are necessary but not sufficient for
  detecting all leakage classes (e.g. qualitative future knowledge)
- statistical: the null-task slice is small (17); we report exact counts and
  invite pooled replications rather than over-claiming
- extraction: pattern-based v0.1 claim extraction is sensitive to
  LaTeX/markdown formatting; an LLM-assisted extractor is planned
- external: single backbone reported here; harness is model-agnostic and
  second/third model replications are in progress **[TODO §5.5]**
- coverage: US filings only; non-US markets require adapters whose data
  licensing must be evaluated per jurisdiction

## 8. Related Work

[expand from research doc: FinGPT / FinRobot / FinRL / TradingAgents;
FinanceBench / FinBen / InvestorBench / FinanceAgent; leakage literature:
Glasserman & Lin, Look-Ahead-Bench, KTD-Fin, FinCAD, Alpha Illusion; open
questions they leave open]

## 9. Conclusion and Roadmap

[rolling walk-forward evaluations; third-party framework audits; dataset and
leaderboard release; ablative study of gating layers]

## References

[todo — full citation list]

## Appendix A. Task generation templates

[the exact question templates and perturbation factors]

## Appendix B. Reproduction

[commands: generate / freeze / run / leak; hardware; API versions; total
cost accounting from the spend ledger]
