#!/usr/bin/env bash
# Linux/macOS: ./start.sh  (instale antes: python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
#                           && (cd frontend && npm install && npm run build))
set -e
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
cd backend
exec python -m app "$@"
