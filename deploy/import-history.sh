#!/bin/bash
# Imports the historical spreadsheet exports into the running app container.
# The CSV files are untracked (personal data stays out of git); copy them to
# /opt/usage by hand (scp) and this runs the same locally and in production.
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
from usage.structures.app_exception import AppException
try:
    print(ImportCommand(Database(SettingsLoader().load())).run(Path('/tmp/$file'), '$house'))
except AppException as exception:
    print(f'⚠️  {exception.message}')
"
}

import_mileage() {  # file house label
    local file="$1" house="$2" label="$3"
    if [ ! -f "$file" ]; then
        echo "⚠️  $file not found - skipping $label."
        return
    fi
    $COMPOSE cp "$file" "$APP:/tmp/$file"
    $COMPOSE exec -T "$APP" python -c "
from pathlib import Path
from usage.commands.import_command import ImportCommand
from usage.libraries.database import Database
from usage.libraries.settings_loader import SettingsLoader
from usage.structures.app_exception import AppException
try:
    print(ImportCommand(Database(SettingsLoader().load())).import_mileage(Path('/tmp/$file'), '$house', '$label'))
except AppException as exception:
    print(f'⚠️  {exception.message}')
"
}

import_one "fremur_edf_gdf_eau.csv" "Fremur"
import_one "dougmar_edf_gdf_eau.csv" "Dougmar"
import_mileage "dougmar_volvo.csv" "Dougmar" "Volvo"
echo "✅ Import finished."
