#!/bin/bash
# Deploy from this machine: nothing is copied. The script checks that what you
# see is what the server will get, then runs deploy-prod.sh over ssh, naming
# the branch so the server refuses to deploy any other.
# Run from anywhere inside the repository.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVER="${SERVER:-ubuntu@45.85.249.159}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/rockview-us-west-2-20260206.pem}"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
REMOTE_SCRIPT="/opt/usage/deploy/deploy-prod.sh"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" = "HEAD" ]; then
    echo "❌ Detached HEAD — check out the branch to deploy."
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes here will NOT be deployed (the server pulls origin/$BRANCH)."
fi
git fetch -q origin "$BRANCH"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]; then
    echo "❌ Local $BRANCH differs from origin/$BRANCH — push (or pull) first."
    exit 1
fi
if [ "$BRANCH" != "main" ]; then
    read -r -p "⚠️  Deploy branch '$BRANCH' (not main) to production? [y/N] " answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "Aborted."; exit 1 ;; esac
fi

echo "🚀 Deploying origin/$BRANCH ($(git rev-parse --short HEAD)) on ${SERVER} ..."
ssh "${SSH_OPTS[@]}" "$SERVER" "DEPLOY_BRANCH='${BRANCH}' bash ${REMOTE_SCRIPT}"
