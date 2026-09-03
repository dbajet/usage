#!/bin/bash
# Production deployment for Usage — blue/green, modeled on Our Stories.
# Runs on the server from the git clone in /opt/usage: the deploy pulls the
# current branch, so production always runs the last pushed commit.
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

# Run as the clone's owner or not at all. Root half-ran the Our Stories script
# once: git called the ubuntu-owned clone "dubious", the pull skipped in
# silence, and the deploy built stale code. Refuse up front, with the fix.
REPO_OWNER="$(stat -c %U .)"
if [ "$(id -un)" != "$REPO_OWNER" ]; then
    echo "❌ This clone belongs to '$REPO_OWNER' but you are '$(id -un)'."
    echo "   Run it as the owner:  sudo -u $REPO_OWNER bash -c 'cd $(pwd) && bash deploy/deploy-prod.sh'"
    exit 1
fi

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

echo "📥 Step 1: Pulling latest code..."
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not a git repository. Production deploys the committed code:"
    echo "   git clone git@github.com:dbajet/usage.git /opt/usage"
    exit 1
fi
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "  branch: $BRANCH"
# The caller names the branch it verified as pushed: deploying a different one
# would look green while shipping somebody else's code.
if [ -n "${DEPLOY_BRANCH:-}" ] && [ "$DEPLOY_BRANCH" != "$BRANCH" ]; then
    echo "❌ This clone is on '$BRANCH' but the deploy asked for '$DEPLOY_BRANCH'."
    echo "   git -C $(pwd) checkout $DEPLOY_BRANCH"
    exit 1
fi
# Committed code only. A fast-forward alone would not catch an edit made on
# the server when the branch has nothing new to bring: the merge says "already
# up to date" and the build takes the edit with it. Ignored files - .env, the
# CSV exports - do not count as changes.
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ The clone has local changes; production builds only what is committed."
    echo "   git -C $(pwd) status"
    exit 1
fi
# Fast-forward only: a local commit in the clone stops the deploy here rather
# than quietly merging, or worse, building something nobody reviewed.
git fetch --quiet origin "$BRANCH"
if ! git merge --ff-only "origin/$BRANCH"; then
    echo "❌ The clone cannot fast-forward onto origin/$BRANCH."
    echo "   It carries local commits or changes:  git -C $(pwd) status"
    exit 1
fi
echo ""

echo "🗄️  Step 2: Ensuring database and backups are up..."
$COMPOSE up -d --build usage-db usage-backup
echo ""

echo "🔨 Step 3: Building the new image (current version still serving)..."
export BUILD_TIME="$(date -u +%Y%m%d-%H%M%SZ)"     # static-asset cache-buster
CDATE="$(git log -1 --format=%cd --date=format:'%Y-%m-%d')"
export APP_VERSION="${CDATE}.$(git log --format=%cd --date=format:'%Y-%m-%d' | grep -c "^${CDATE}$")"
echo "  build: $BUILD_TIME   version: $APP_VERSION"

FROM="$(active_colour)"
TO="$(other_of "$FROM")"
$COMPOSE build "usage-app-${TO}"
echo ""

echo "🎨 Step 4: $FROM ➜ $TO"
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

echo "🫗  Step 5: Stopping $FROM..."
$COMPOSE stop "usage-app-${FROM}"
echo "  ✅ $FROM stopped"
echo ""

echo "🧹 Step 6: Pruning old dangling images (keeping the last week)..."
docker image prune -f --filter "until=168h" > /dev/null
echo ""

echo "========================================="
echo "✅ Deployment complete — serving from $TO"
echo "========================================="
$COMPOSE ps
echo ""
echo "  App:    https://usage.edgy.world"
echo "  Logs:   docker compose logs -f usage-app-${TO}"
