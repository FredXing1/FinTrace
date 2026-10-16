#!/bin/sh
# Run the PITfall ablation arms against a LOCAL OpenAI-compatible endpoint
# (llama-server, ollama, or vLLM). Every arm runs on this machine at zero API
# cost, and all self-run experiments stay on the frozen core-200.
#
# Usage:
#   FINTRACE_LLM_BASE_URL=http://localhost:8080/v1 \
#   FINTRACE_LLM_MODEL=qwen2.5-7b-instruct-q4_k_m \
#   scripts/ablation-local.sh
#
# Environment:
#   FINTRACE_LLM_BASE_URL  local endpoint (required)
#   FINTRACE_LLM_MODEL     model name (required)
#   CORE                   task file      (default data/pitfall/core.jsonl)
#   OUT                    report dir     (default data/pitfall/ablation)
#   ARMS                   arms to run    (default: all six, report order)
#   TIMEOUT                per-call seconds (default 600 for long local prefills)
set -eu

: "${FINTRACE_LLM_BASE_URL:?set FINTRACE_LLM_BASE_URL, e.g. http://localhost:8080/v1}"
: "${FINTRACE_LLM_MODEL:?set FINTRACE_LLM_MODEL, e.g. qwen2.5-7b-instruct-q4_k_m}"
CORE="${CORE:-data/pitfall/core.jsonl}"
OUT="${OUT:-data/pitfall/ablation}"
ARMS="${ARMS:-full gate-off prompt-off neither no-tools single-shot}"
TIMEOUT="${TIMEOUT:-600}"
FINTRACE="${FINTRACE_BIN:-$(dirname "$0")/../.venv/bin/fintrace}"
[ -x "$FINTRACE" ] || FINTRACE=fintrace

mkdir -p "$OUT"
tag=$(echo "$FINTRACE_LLM_MODEL" | tr ':' '-')

for arm in $ARMS; do
  report="$OUT/report-$tag-$arm.json"
  if [ -f "$report" ]; then
    echo "=== arm $arm: already done ($report), skipping"
    continue
  fi
  echo "=== arm: $arm -> $report"
  "$FINTRACE" pitfall-run \
    --tasks "$CORE" \
    --arm "$arm" \
    --model "$FINTRACE_LLM_MODEL" \
    --timeout "$TIMEOUT" \
    --out "$report"
done
echo "all requested arms finished; reports in $OUT"
