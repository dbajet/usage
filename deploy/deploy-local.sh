#!/bin/bash
# Local development deployment: rebuild and restart the app container with the
# local .env, wait for it to become healthy, and print the URL.
#
# Deploys the colour already running locally (green if it is up, blue
# otherwise); override with USAGE_LOCAL_COLOUR=blue|green.
# Run from anywhere inside the repository.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose"

COLOUR="${USAGE_LOCAL_COLOUR:-}"
if [ -z "$COLOUR" ]; then
    if docker ps --format '{{.Names}}' | grep -q '^usage-app-green$'; then
        COLOUR=green
    else
        COLOUR=blue
    fi
fi
APP="usage-app-${COLOUR}"

echo "========================================="
echo "  Usage — Local Deployment ($COLOUR)"
echo "========================================="
echo ""

if [ ! -f .env ]; then
    echo "❌ .env not found. Copy .env.example to .env and fill in the secrets."
    exit 1
fi

export BUILD_TIME="$(date -u +%Y%m%d-%H%M%SZ)"     # static-asset cache-buster
export APP_VERSION="${APP_VERSION:-local-$(date -u +%Y-%m-%d)}"
echo "  build: $BUILD_TIME   version: $APP_VERSION"
echo ""

echo "🗄️  Step 1: Ensuring the database is up..."
$COMPOSE up -d usage-db
echo ""

echo "🔨 Step 2: Building and starting ${APP}..."
$COMPOSE up -d --build "$APP"
echo ""

echo "🏥 Step 3: Waiting for the app to become healthy..."
BIND="$($COMPOSE port "$APP" 8063)"
PORT="${BIND##*:}"
healthy=""
for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" 2>/dev/null | grep -q '"ok":true'; then healthy=1; break; fi
    sleep 2
done
if [ -z "$healthy" ]; then
    echo "❌ The app did not become healthy. Recent logs:"
    $COMPOSE logs --tail=50 "$APP"
    exit 1
fi

echo "✅ Usage is running at http://localhost:${PORT}"
