#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -m venv "$ROOT_DIR/.venv"
# shellcheck disable=SC1090
source "$ROOT_DIR/.venv/bin/activate"

pip install --upgrade pip
pip install -r "$ROOT_DIR/scanning/requirements.txt"
pip install -r "$ROOT_DIR/animations/requirements.txt"

echo "Virtual env ready. Activate with: source $ROOT_DIR/.venv/bin/activate"
