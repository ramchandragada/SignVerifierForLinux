#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Virtualenv missing. Create it with:"
  echo "  python3 -m venv --without-pip .venv"
  echo "  curl -fsSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python"
  echo "  .venv/bin/pip install -r requirements.txt"
  exit 1
fi

exec "$ROOT/.venv/bin/python" "$ROOT/main.py" "$@"
