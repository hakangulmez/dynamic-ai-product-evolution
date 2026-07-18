#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .venv/bin/activate ]; then
  echo "Missing .venv. Run ./scripts/setup_local.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec streamlit run apps/research_console/app.py
