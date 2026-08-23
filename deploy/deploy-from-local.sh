#!/bin/bash
# Pushes the working tree to the production server and runs the blue/green
# deployment there. Run from anywhere inside the repository.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="${SERVER:-ubuntu@45.85.249.159}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/rockview-us-west-2-20260206.pem}"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

APP_VERSION="$(git log -1 --format=%cd --date=format:'%Y-%m-%d' 2>/dev/null || date -u +%Y-%m-%d)"

echo "📤 Syncing working tree to ${SERVER}:/opt/usage ..."
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
    --exclude ".git" --exclude ".env" --exclude "__pycache__" \
    --exclude ".pytest_cache" --exclude ".mypy_cache" --exclude ".ruff_cache" \
    --exclude ".venv" \
    ./ "${SERVER}:/opt/usage/"

echo "🚀 Running the blue/green deployment on the server..."
ssh "${SSH_OPTS[@]}" "$SERVER" "APP_VERSION='${APP_VERSION}' bash /opt/usage/deploy/deploy-prod.sh"
