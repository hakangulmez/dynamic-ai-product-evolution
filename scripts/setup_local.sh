#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.11+ and run this script again." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,notebook,ui]'

cat <<'EOF'

Local environment is ready.

Activate it in a new terminal with:
  source .venv/bin/activate

Launch the Streamlit setup console with:
  make ui

Launch the master notebook with:
  make notebook

For Obsidian, install the desktop app and open this repository folder as a vault.
Then open RESEARCH_HOME.md.
EOF
