#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -d ".venv" ]]; then
  source .venv/bin/activate
fi

python scripts/run_daily.py \
  --journal-preset "${JOURNAL_PRESET:-cns_high_impact}" \
  --days-back "${DAYS_BACK:-7}" \
  --min-gated "${MIN_GATED_PAPERS:-5}" \
  --max-days-back "${MAX_DAYS_BACK:-35}" \
  --expand-step-days "${EXPAND_STEP_DAYS:-7}" \
  --llm-limit "${LLM_REVIEW_LIMIT:-10}" \
  "$@"
