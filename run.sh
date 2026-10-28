#!/usr/bin/env bash
# Starts AutoGrade-RDF: one local server for the API (/api) and the web pages (web/). Usage: ./run.sh [port]
set -euo pipefail
cd "$(dirname "$0")"
command -v conda >/dev/null || { echo "conda not found: install Miniconda and create the semantic_web env (README, Setup)" >&2; exit 1; }

autograde() { conda run --no-capture-output -n semantic_web python -m autograde "$@"; }

# The first start fills the database from data/ (the demo course); later starts keep what was entered in the app.
[ -e "${AUTOGRADE_DB_DIR:-db}/autograde.sqlite" ] || autograde db import
autograde serve --port "${1:-8000}"
