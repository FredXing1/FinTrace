# Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/) (or plain pip).

```bash
git clone https://github.com/FredXing1/FinTrace.git && cd FinTrace
make setup        # toolchain install
make check        # ruff + mypy + pytest

# build the PIT data layer from public EDGAR bulk data
export FINTRACE_SEC_UA="your-name contact@example.com"   # SEC requires a contact UA
fintrace download companyfacts
fintrace ingest companyfacts          # ~125M facts, run in background
fintrace ingest-tickers
```

## Your first point-in-time query

Every query takes a **mandatory** `as_of` date — asking "what was knowable at
T" is the core contract of this library:

```bash
uv run fintrace query-fact --ticker AAPL --tag Revenues \
    --period-end 2022-09-24 --as-of 2023-01-01
```

- as of 2022-10-01 the answer is `null` — FY2022 revenue was not filed yet;
- as of 2023-01-01 you get $394,328M with the accession number of the 10-K
  that disclosed it;
- if a later 10-K restates the figure, the vintage switches automatically at
  its filing date (restatement-aware).

## Run the agent

```bash
export FINTRACE_LLM_BASE_URL=https://api.deepseek.com \
       FINTRACE_LLM_API_KEY=... FINTRACE_LLM_MODEL=deepseek-chat
uv run fintrace agent "How did Apple's revenue trend?" --as-of 2023-06-30
```

The loop is fully traced (`data/traces/`), every LLM call passes a budget
governor, and identical calls hit the response cache. Convert any trace into
an [auditpack](auditpack.md): `fintrace audit data/traces/<run>.json`.

## Evaluate a model on PITfall

```bash
uv run fintrace pitfall-generate                       # pool 579 + frozen core-200
uv run fintrace pitfall-run --tasks data/pitfall/core.jsonl --out report.json
uv run fintrace pitfall-leak --tasks data/pitfall/core.jsonl --gated-report report.json
```

Prefer zero API cost? Point the same commands at a local OpenAI-compatible
server (Ollama works out of the box):
`FINTRACE_LLM_BASE_URL=http://localhost:11434/v1 FINTRACE_LLM_API_KEY=ollama`.
The ablation matrix runs entirely this way — see
`scripts/ablation-local.sh`.

## One-command deployment

```bash
docker compose -f deploy/docker-compose.yml up --build
# demo app on :8501, docs on :8000, Prometheus metrics on :9091
```
