# FinTrace: Point-in-Time Guardrails and a Leakage-Controlled Benchmark for Financial LLM Agents

**Technical Report — v0.1 draft** · 2026-09 · Apache-2.0 · code at `github.com/FredXing1/FinTrace`

> Status: v0.2. Numbers in §5.2–§5.5 are final measured results. Remaining
> [TODO] entries are prose expansions (related work, appendices), not
> pending runs.

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
50% to 80%. A six-arm ablation isolates the mechanism: with structural tool
gating removed but the discipline prompt kept, 35% of impossible tasks still
leak; with the gate kept and the prompt removed, 6% — prompt discipline alone
does not prevent tool-borne look-ahead. All three audit configurations cost
under ¥5 (~$0.7) in total LLM fees and the ablation matrix runs on local
open-weights inference at zero API cost; the entire pipeline is reproducible
byte-for-byte from public EDGAR data.

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
5. An ablation matrix that decomposes the protection into structural tool
   gating, prompt discipline, and loop depth: prompt discipline alone leaves
   35% of impossible tasks leaking; the structural gate alone leaves 6%;
   the full system leaks 0. **[§5.4]**
6. **auditpack v0.1**: an open JSON Schema for auditable agent output —
   conclusion, per-claim verdicts, evidence chain, execution log, human
   sign-off. **[§6]**
7. A cost-disciplined protocol: the full 200-task gated baseline plus a
   200-task ungated audit cost ≈ ¥4.4 (~$0.6) in LLM fees; the ablation
   matrix runs entirely on local open-weights inference at zero API cost.
   **[§5.1, §5.4]**

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

### 5.4 Ablations: which layer actually prevents leakage?

The gated agent bundles three protection layers: (i) **structural tool
gating** — every tool is `as_of`-bounded and physically cannot return a
post-`T` fact; (ii) **prompt discipline** — the system prompt states the
cutoff and prescribes "unknown" for anything not public; (iii) the
**multi-step loop** that lets the agent iterate tool calls. We run six arms
that remove these layers factorially, on the frozen core-200, with a local
open-weights backbone (Qwen2.5-7B-Instruct, Q4_K_M quantization, served
locally, temperature 0, zero API cost) so that every arm difference is
attributable to the removed layer and not to a change of model.

| arm | gate | prompt | loop | T1 | T2 | T3 | T1-null leak | med. lat. |
|---|---|---|---|---|---|---|---|---|
| full | ✓ | ✓ | multi-step | 50% | 68.3% | 0% | **0/17** | 9.6s |
| gate-off (prompt only) | – | ✓ | multi-step | 40% | 73.3% | 37.5% | **6/17 (35.3%)** | 9.5s |
| prompt-off (gate only) | ✓ | – | multi-step | 25% | 50.0% | 15% | 1/17 (5.9%) | 6.9s |
| neither (naive pattern) | – | – | multi-step | 19% | 56.7% | 20% | 2/17 (11.8%) | 6.8s |
| no-tools | – | ✓ | single call | 17% | 35.0% | 0% | 0/17 | 1.2s |
| one-round | ✓ | ✓ | one tool round | 50% | 68.3% | 0% | 0/17 | ≤9.6s |

Findings:

1. **Prompt discipline alone does not prevent tool-borne leakage.** With the
   structural gate removed but the discipline prompt kept, the agent leaked
   6/17 impossible tasks (35.3%) — and answered a specific value on 7/17. The
   system prompt stated the cutoff and prescribed "unknown"; the model
   retrieved the latest, post-`T` value through the tool anyway and reported
   it. A prompt shapes *framing*; it does not change *information access*.
2. **Structural gating is the load-bearing layer.** With the gate in place
   and the discipline prompt removed, leakage falls to 1/17 (5.9%); the full
   system leaks 0/17. Once the tool cannot return future facts, the only
   remaining channel is training memory (the bare-model rate, §5.3), and the
   discipline prompt closes even that residual.
3. **Ungated access manufactures apparent forecasting skill.** gate-off
   scores 37.5% on T3 forward estimation vs 0% for the identical model under
   the full gate — the "forecast" is retrieval of the realized value, the
   same illusion documented cross-model in §5.3.
4. **Loop depth is not a protection mechanism.** one-round reproduces full
   exactly on every family: for this backbone the answer is decided by the
   first tool round; additional reflection steps change nothing.
5. **Memory-only leakage is model-dependent.** The naive arm answers a value
   on 13/17 impossible tasks but only 2 match the realized value — this
   backbone hallucinates more than it remembers. Absolute capability is far
   below the API backbone of §5.2 (T1 50% vs 92%); the ablation is read as
   *within-model* differences across arms, and the gate ≫ prompt ordering is
   the invariant we report.

Arms share the response cache for byte-identical calls (temperature 0), so
genuinely identical prefixes are computed once; no cross-model contamination
is possible because cache keys include the model name. Total ablation cost:
¥0 (local inference, ~7–10 s per task on an Apple M2).

### 5.6 Third-party framework audit: TradingAgents v0.6.0

The naive-agent pattern of §5.3 was modeled on TradingAgents, the most-
referenced open-source multi-agent trading framework. A code-level audit of
v0.6.0 (`reports/tradingagents-audit.md`) finds the framework has since
shipped a genuine point-in-time layer — as-filed SEC EDGAR statements
(`filed ≤ as_of`, restatement-aware), price paths bounded at the as-of date,
FRED macro vintages, conservative news/social window filtering, and live
snapshots withheld from historical runs. Remaining gaps: an unguarded
identity-context surface (today's profile injected into every run), a
withhold-not-serve posture that degrades historical backtests and invites
users back to live-data mode, per-surface rather than structural time
discipline, and no in-repo measurement that would catch a leakage regression.
The audit is code-level only; we make no claim about behavior beyond the
audited commit, and none of this is investment advice.

### 5.5 Second-model replication

The leakage audit of §5.3 was replicated with GLM-4.7 (thinking disabled) as
the bare model: **2/17 (11.8%) of impossible tasks answered with the true
future value — identical to deepseek-chat** — with T1 2%, T2 55%, T3 12.5%.
Two model families from different vendors produce the same memory-leakage
rate, supporting the claim that look-ahead leakage is a property of the
*evaluation setup* (no gate, no unknown escape hatch), not of a particular
model. Third-family replication is covered by the local open-weights backbone
of §5.4, which exhibits the same qualitative pattern under the factorial
arms.

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
- external: §5.2–§5.3 use a single API backbone (deepseek-chat) plus a
  second-family replication (GLM-4.7, §5.5); the ablation matrix (§5.4) uses
  a single local open-weights backbone at Q4 quantization, whose absolute
  accuracy is far lower — ablation conclusions are within-model arm
  differences, not absolute-score claims
- coverage: US filings only; non-US markets require adapters whose data
  licensing must be evaluated per jurisdiction

## 8. Related Work

[expand from research doc: FinGPT / FinRobot / FinRL / TradingAgents;
FinanceBench / FinBen / InvestorBench / FinanceAgent; leakage literature:
Glasserman & Lin, Look-Ahead-Bench, KTD-Fin, FinCAD, Alpha Illusion; open
questions they leave open]

## 9. Conclusion and Roadmap

[rolling walk-forward evaluations; third-party framework audits (TradingAgents
v0.6.0 done, §5.6); dataset and leaderboard release; ablative study of gating
layers done (§5.4)]

## References

[todo — full citation list]

## Appendix A. Task generation templates

[the exact question templates and perturbation factors]

## Appendix B. Reproduction

```sh
# 1. data layer (public SEC EDGAR; declare a contact UA)
export FINTRACE_SEC_UA="your-project contact-email"
fintrace download companyfacts && fintrace ingest companyfacts
fintrace ingest-tickers

# 2. benchmark: generate, freeze core-200 (deterministic, sha256 manifest)
fintrace pitfall-generate                       # -> data/pitfall/{pool,core,manifest}

# 3. gated baseline (any OpenAI-compatible endpoint)
export FINTRACE_LLM_BASE_URL=https://api.deepseek.com FINTRACE_LLM_API_KEY=... FINTRACE_LLM_MODEL=deepseek-chat
fintrace pitfall-run --tasks data/pitfall/core.jsonl --out report.json

# 4. leakage audit (bare model, no as-of framing)
fintrace pitfall-leak --tasks data/pitfall/core.jsonl --gated-report report.json --out leak.json

# 5. ablation matrix (local open-weights, zero API cost)
FINTRACE_LLM_BASE_URL=http://localhost:11434/v1 \
FINTRACE_LLM_API_KEY=ollama FINTRACE_LLM_MODEL=qwen2.5:7b \
scripts/ablation-local.sh       # six arms -> data/pitfall/ablation/
```

Hardware: Apple M2 (24 GB) for local inference; scoring is deterministic
(pattern/numeric matching, no LLM judge) with 2000-resample bootstrap CIs.
Total API-model spend for §5.2–§5.3: ≈ ¥4.4 from the budget governor's
ledger; §5.4–§5.5: ¥0. Reports referenced in this text:
`data/pitfall/report-deepseek-core200.json`,
`data/pitfall/report-deepseek-core200-ungated.json`,
`data/pitfall/leak-deepseek-core200.json`,
`data/pitfall/leak-glm47-core200.json`,
`data/pitfall/ablation/report-qwen2.5-7b-*.json`.
