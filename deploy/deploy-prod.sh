#!/bin/bash
# Production deployment for Usage — blue/green, modeled on Our Stories.
# Runs on the server from /opt/usage (code arrives there via rsync).
#
# Two identical app containers exist; nginx points at one. A deploy builds the
# image, starts the *idle* colour, health-checks it, switches nginx, then stops
# the old colour. Requests already in flight finish on the old worker during
# the nginx reload; new requests go to the new colour.
#
# Both colours share one database: the new version runs its migrations at
# startup while the old version is still serving, so a migration must stay
# readable by BOTH versions for the seconds of overlap (additive changes only).
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/sites-available/usage.edgy.world}"
BLUE_PORT=8063
GREEN_PORT=8064

port_of()  { [ "$1" = "blue" ] && echo "$BLUE_PORT" || echo "$GREEN_PORT"; }
other_of() { [ "$1" = "blue" ] && echo "green" || echo "blue"; }
health()   { curl -fsS "http://127.0.0.1:$(port_of "$1")/healthz" 2>/dev/null; }

# Which colour nginx currently sends traffic to.
active_colour() {
    if grep -qE "^[[:space:]]*server 127\.0\.0\.1:${GREEN_PORT};" "$NGINX_CONF" 2>/dev/null; then
        echo green
    else
        echo blue
    fi
}

point_nginx_at() {  # colour
    local port; port="$(port_of "$1")"
    # Delimiter is @: the pattern contains an alternation, and | would end it.
    sudo sed -i -E "s@^([[:space:]]*)server 127\.0\.0\.1:(${BLUE_PORT}|${GREEN_PORT});.*@\1server 127.0.0.1:${port};   # $1@" "$NGINX_CONF"
    sudo nginx -t > /dev/null
    sudo nginx -s reload
}

echo "========================================="
echo "  Usage — Production Deployment"
echo "========================================="
echo ""

if [ ! -f .env ]; then
    echo "❌ .env not found in /opt/usage."
    exit 1
fi

echo "🗄️  Step 1: Ensuring database and backups are up..."
$COMPOSE up -d --build usage-db usage-backup
echo ""

echo "🔨 Step 2: Building the new image (current version still serving)..."
export BUILD_TIME="$(date -u +%Y%m%d-%H%M%SZ)"     # static-asset cache-buster
export APP_VERSION="${APP_VERSION:-$(date -u +%Y-%m-%d)}"
echo "  build: $BUILD_TIME   version: $APP_VERSION"

FROM="$(active_colour)"
TO="$(other_of "$FROM")"
$COMPOSE build "usage-app-${TO}"
echo ""

echo "🎨 Step 3: $FROM ➜ $TO"
echo "  starting $TO…"
$COMPOSE up -d --no-deps "usage-app-${TO}"

healthy=""
for _ in $(seq 1 40); do
    if health "$TO" | grep -q '"ok":true'; then healthy=1; break; fi
    sleep 2
done
if [ -z "$healthy" ]; then
    echo "  ❌ $TO did not become healthy. Recent logs:"
    $COMPOSE logs --tail=50 "usage-app-${TO}"
    $COMPOSE stop "usage-app-${TO}" || true
    echo "  ↩️  nothing switched — $FROM is still serving the site."
    echo "  Deploy FAILED — fix the build, then redeploy."
    exit 1
fi
echo "  ✅ $TO healthy"

echo "  switching nginx to $TO…"
point_nginx_at "$TO"
echo "  ✅ $TO is live"
echo ""

echo "🫗  Step 4: Stopping $FROM..."
$COMPOSE stop "usage-app-${FROM}"
echo "  ✅ $FROM stopped"
echo ""

echo "🧹 Step 5: Pruning old dangling images (keeping the last week)..."
docker image prune -f --filter "until=168h" > /dev/null
echo ""

echo "========================================="
echo "✅ Deployment complete — serving from $TO"
echo "========================================="
$COMPOSE ps
echo ""
echo "  App:    https://usage.edgy.world"
echo "  Logs:   docker compose logs -f usage-app-${TO}"
