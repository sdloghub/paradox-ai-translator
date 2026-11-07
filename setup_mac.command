#!/bin/zsh
set -e
cd "${0:A:h}"
print "Starting Paradox AI Translator: $PWD"
print "Entry Browser: browse and edit translation entries directly."
if [[ ! -x .venv/bin/python ]]; then
  echo "Initializing Python virtual environment (.venv)..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import openai' >/dev/null 2>&1; then
  echo "Installing dependencies (requirements.txt)..."
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python workshop_app.py "$@"
