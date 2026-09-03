#!/bin/bash
# Triggers the blue/green deployment on the production server. The server
# deploys the last pushed commit of its current branch (deploy-prod.sh pulls
# it), so push first — nothing is copied from this machine.
# Run from anywhere inside the repository.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="${SERVER:-ubuntu@45.85.249.159}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/rockview-us-west-2-20260206.pem}"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes will NOT be deployed (the server pulls from origin)."
fi
git fetch -q origin "$BRANCH"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
    echo "❌ Local $BRANCH differs from origin/$BRANCH — push (or pull) first."
    exit 1
fi

echo "🚀 Running the blue/green deployment on ${SERVER} (/opt/usage)..."
ssh "${SSH_OPTS[@]}" "$SERVER" "DEPLOY_BRANCH='${BRANCH}' bash /opt/usage/deploy/deploy-prod.sh"
