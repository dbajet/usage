#!/bin/bash
# Imports a SwitchBot meter's own history into the thermometer it belongs to.
#
# SwitchBot's cloud serves no history, but every meter keeps 36 days on itself
# (68 on a Meter Plus or an Outdoor one). The phone reads that over Bluetooth -
# open the device in the SwitchBot app, "Load History", then "Export Data" -
# and writes a CSV named after the device. Copy those files next to this
# repository and run:
#
#     ZONE=America/Los_Angeles bash deploy/import-switchbot.sh Fremur "Cave à vin 05_data.csv" ...
#
# ZONE is the clock the export was written on, which is the *exporting phone's*
# and not the house's - an export of French thermometers taken on a phone in
# California is nine hours out, and the readings look perfectly reasonable
# sitting in the wrong hours. It defaults to the house's own zone, which is
# right only when the phone was in the house.
#
# The house is named once and the files name their own devices, so the six
# exports of a house go in one line. A sensor renamed in Settings since it
# arrived is the one case that needs saying out loud; pass it as
# "file.csv=The Cellar".
#
# Running it twice costs nothing: readings are keyed by sensor and instant, and
# anything the app collected itself is left exactly as it was.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose"
APP="$($COMPOSE ps --status running --services | grep -E '^usage-app-(blue|green)$' | head -1)"
if [ -z "$APP" ]; then
    echo "❌ No running usage-app container. Start one first."
    exit 1
fi
if [ "$#" -lt 2 ]; then
    echo "Usage: bash deploy/import-switchbot.sh <house> <export.csv>[=<sensor name>] ..."
    exit 1
fi

HOUSE="$1"
ZONE="${ZONE:-}"
shift

import_one() {  # file sensor
    local file="$1" sensor="$2"
    if [ ! -f "$file" ]; then
        echo "⚠️  $file not found - skipping."
        return
    fi
    # Basename inside the container: the command reads the device's name off it.
    local remote="/tmp/$(basename "$file")"
    $COMPOSE cp "$file" "$APP:$remote"
    $COMPOSE exec -T "$APP" python -c "
from pathlib import Path
from usage.commands.switch_bot_import_command import SwitchBotImportCommand
from usage.libraries.database import Database
from usage.libraries.settings_loader import SettingsLoader
from usage.structures.app_exception import AppException
try:
    print(SwitchBotImportCommand(Database(SettingsLoader().load())).run(Path('''$remote'''), '''$HOUSE''', '''$sensor''', '''$ZONE'''))
except AppException as exception:
    print(f'⚠️  {exception.message}')
"
}

for argument in "$@"; do
    case "$argument" in
        *=*) import_one "${argument%%=*}" "${argument#*=}" ;;
        *)   import_one "$argument" "" ;;
    esac
done
echo "✅ Import finished."
