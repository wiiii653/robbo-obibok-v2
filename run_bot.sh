#!/usr/bin/env bash
# Wrapper to start Robbo Obibok v2
set -euo pipefail

cd "$(dirname "$0")"

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$PWD"
exec ./venv/bin/python3 -u -m src
