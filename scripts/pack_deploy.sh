#!/usr/bin/env bash
# Gera arquivo compacto sem .git / venv para SCP à VPS
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$(dirname "$ROOT")/deriv-ai-bot-deploy.tgz"
tar -czvf "$OUT" \
  --exclude=".git" \
  --exclude="venv" \
  --exclude=".venv" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude="node_modules" \
  --exclude="web/node_modules" \
  --exclude="web/dist" \
  --exclude="data" \
  --exclude=".env" \
  .
echo "Criado: $OUT"
