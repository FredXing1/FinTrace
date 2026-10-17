# FinTrace · PITfall

Auditable, point-in-time financial research agents & the PITfall leakage-controlled
benchmark — every claim traceable to as-filed evidence, zero look-ahead.

> **v1.0** — feature-complete research software. ⚠️ Measurement instrument, not investment advice.

🧪 **Live demo** (no sign-up, no API key): [fintrace-demo.streamlit.app](https://fintrace-demo.streamlit.app) —
pick a company, a metric, and a knowledge cutoff; watch the point-in-time answer vs what a naive live-data API returns.

![FinTrace time-travel demo](docs/assets/demo.gif)

- 📍 **Status**: **v1.0, complete.** 125M as-filed facts; frozen core-200
  benchmark (T1 92% / T2 93.3% / T3 50%, bootstrap 95% CI); leakage audit
  showing a naive live-data agent answers **82% of "impossible" questions
  with the true future value** while the gated agent leaks **0**; and a
  six-arm ablation isolating *why* — prompt discipline alone still leaks 35%,
  the structural gate is what actually works (0%). See
  [`docs/00-STATE.md`](docs/00-STATE.md).
- 💡 Total LLM cost of all API-reported runs: **≈ ¥4.4 (~$0.6)**; the ablation
  matrix runs on local open-weights models at zero API cost.

## What's inside

| Module | Purpose |
|---|---|
| `fintrace-data` | Point-in-time EDGAR ingestion: as-filed XBRL facts gated by `filed` timestamps |
| `as_of(T)` | The PIT query primitive shared by runtime and benchmark — no default, no look-ahead |
| `pitfall-bench` | Leakage-controlled benchmark: time-gated QA, claim verification, forward estimation |
| `auditpack` | Open audit-trail schema: claims + evidence chains + execution logs + sign-off |

📄 Technical report (v1.0): [`reports/technical-report.md`](reports/technical-report.md)
🔎 Third-party audit: TradingAgents v0.6.0 point-in-time review — [`reports/tradingagents-audit.md`](reports/tradingagents-audit.md)
🤗 Benchmark dataset: [huggingface.co/datasets/Fredxing/pitfall](https://huggingface.co/datasets/Fredxing/pitfall)

## Results — same benchmark, three configurations

Frozen core-200 (T1×100 incl. 17 *impossible* tasks whose answers were not
public at the reference date / T2×60 / T3×40), deepseek-chat backbone,
bootstrap 95% CIs in the [technical report](reports/technical-report.md).

| configuration | impossible tasks answered with the TRUE future value | T1 time-gated QA | T2 claim verification | T3 forward estimation¹ |
|---|---|---|---|---|
| bare model (GLM-4.7, no tools) | 2/17 (11.8%) | 2% | 55.0% | 12.5% |
| bare model (deepseek-chat, no tools) | 2/17 (11.8%) | 5% | 53.3% | 25.0% |
| naive agent (live-data tools, no time gate) | **14/17 (82%)** | 77% | 86.7% | **80%** |
| **gated FinTrace agent** | **0/17** (16/17 correctly "unknown") | **92%** | **93.3%** | 50% |

¹ T3 pass = APE ≤ 20%. The naive agent's T3 "forecasting" jump (50% → 80%)
and the 82% impossible-question leakage are look-ahead access, not
intelligence: on T1-positive tasks the naive agent is flat vs gated
(93% vs 92%). The pattern replicates across both model families.

Reproduce: `fintrace pitfall-generate` → `pitfall-run` → `pitfall-leak`.

## Results — ablations: which layer actually prevents leakage?

Same frozen core-200, local open-weights backbone (Qwen2.5-7B, temperature 0,
zero API cost), six arms removing protection layers factorially:

| arm | structural gate | prompt discipline | multi-step loop | impossible-task leakage |
|---|---|---|---|---|
| **full** | ✓ | ✓ | ✓ | **0/17** |
| gate-off (prompt only) | — | ✓ | ✓ | **6/17 (35.3%)** |
| prompt-off (gate only) | ✓ | — | ✓ | 1/17 (5.9%) |
| neither (naive pattern) | — | — | ✓ | 2/17 (11.8%) |

**Telling the model the cutoff is not enough.** With the gate removed but the
discipline prompt kept, the agent still leaks 35% of impossible tasks — it
retrieves post-cutoff values through the tool and reports them anyway. The
structural gate is the load-bearing layer; loop depth changes nothing.
Full table and findings: [docs](docs/ablations.md) ·
[report §5.4](reports/technical-report.md).

Reproduce the whole matrix on your own machine at zero API cost:
`scripts/ablation-local.sh` (any local OpenAI-compatible server).

## Quick start

```bash
make setup     # toolchain install
make check     # ruff + mypy + pytest

# build the PIT data layer from public SEC EDGAR data
export FINTRACE_SEC_UA="your-name you@example.com"   # SEC requires a contact UA
uv run fintrace download companyfacts
uv run fintrace ingest companyfacts                  # ~125M facts, background job
uv run fintrace ingest-tickers

uv run fintrace query-fact --ticker AAPL --tag Revenues --period-end 2022-09-24 --as-of 2023-01-01
```

Or skip the build entirely — one command starts the demo app, the docs site,
and a Prometheus metrics endpoint:

```bash
docker compose -f deploy/docker-compose.yml up --build   # demo :8501 · docs :8000 · metrics :9091
```

Score a model on the published dataset (forward-estimation gold withheld):

```python
from datasets import load_dataset
core = load_dataset("Fredxing/pitfall", data_files="core-200.jsonl")["train"]
```

Every query takes a mandatory `as_of` date by design: asking "what was knowable
at T" is the core contract of this library.

## License

Apache-2.0


