#!/bin/bash
# Imports the historical spreadsheet exports into the running app container.
# The CSV files are untracked (personal data stays out of git) but rsync
# carries them to /opt/usage, so this runs the same locally and in production.
# The import refuses to run twice: a house that already exists is left alone.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose"
APP="$($COMPOSE ps --status running --services | grep -E '^usage-app-(blue|green)$' | head -1)"
if [ -z "$APP" ]; then
    echo "❌ No running usage-app container. Start one first."
    exit 1
fi

import_one() {  # file house
    local file="$1" house="$2"
    if [ ! -f "$file" ]; then
        echo "⚠️  $file not found - skipping $house."
        return
    fi
    $COMPOSE cp "$file" "$APP:/tmp/$file"
    $COMPOSE exec -T "$APP" python -c "
from pathlib import Path
from usage.commands.import_command import ImportCommand
from usage.libraries.database import Database
from usage.libraries.settings_loader import SettingsLoader
print(ImportCommand(Database(SettingsLoader().load())).run(Path('/tmp/$file'), '$house'))
"
}

import_one "fremur_edf_gdf_eau.csv" "Fremur"
import_one "dougmar_edf_gdf_eau.csv" "Dougmar"
echo "✅ Import finished."
