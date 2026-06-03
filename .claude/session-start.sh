#!/bin/bash
# Session-start hook: ensure Python and Node dependencies are installed.
# Runs at the beginning of every Claude Code session in this project.

POETRY=/root/.local/share/uv/tools/poetry/bin/poetry
PROJECT_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel 2>/dev/null || echo /home/user/lens)"

echo "[session-start] Installing Python dependencies..."
cd "$PROJECT_ROOT"
"$POETRY" install --quiet --no-update

echo "[session-start] Installing Node dependencies..."
cd "$PROJECT_ROOT/lens/server/ui"
npm ci --silent 2>/dev/null || npm ci --silent

echo "[session-start] Done."
