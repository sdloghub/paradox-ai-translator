#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "Starting Paradox AI Translator in: $PWD"
if [ ! -x .venv/bin/python ]; then
  echo "Initializing Python virtual environment (.venv)..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import openai' >/dev/null 2>&1; then
  echo "Installing dependencies (requirements.txt)..."
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python workshop_app.py "$@"
