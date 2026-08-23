#!/bin/bash
# Daily backup for Usage, the our-stories pattern: local day-of-month
# rotation, S3 copy to daily/<app>/<date>/ plus monthly/ on the 1st — and the
# dump is sealed with BACKUP_PASSPHRASE before it ever touches disk, so
# neither the local copy nor the S3 object exposes even the metadata the
# database keeps in plaintext. The sensitive columns inside are already Fernet
# ciphertext under USAGE_ENCRYPTION_KEY; the passphrase is a second,
# independent lock. Keep BOTH in the password manager: a backup needs the
# passphrase to open and the Fernet key to read.
set -euo pipefail

: "${PGPASSWORD:?PGPASSWORD not set}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE not set}"
DB_HOST=${DB_HOST:-usage-db}
DB_USER=${DB_USER:-user_usage}
DB_NAME=${DB_NAME:-db_usage}
BACKUP_ROOT=${BACKUP_ROOT:-/backups}
APP_NAME=${APP_NAME:-usage}

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

count=0
until pg_isready -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
    log "Waiting for database $DB_HOST..."
    sleep 2
    count=$((count + 1))
    if [ $count -ge 30 ]; then
        log "Error: timed out waiting for the database."
        exit 1
    fi
done

day_dir="$(date +%d)"
target_dir="${BACKUP_ROOT}/${day_dir}"
mkdir -p "$target_dir"
out_file="${target_dir}/${DB_NAME}.dump.enc"
tmp_file="${out_file}.tmp"

if pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" \
    | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$tmp_file"; then
    mv "$tmp_file" "$out_file"
    log "Backup written to $out_file"
else
    log "Backup failed for $DB_NAME"
    rm -f "$tmp_file"
    exit 1
fi

if [ -n "${S3_BACKUP_BUCKET:-}" ]; then
    today="$(date +%Y-%m-%d)"
    s3_daily="s3://${S3_BACKUP_BUCKET}/daily/${APP_NAME}/${today}/${DB_NAME}.dump.enc"
    if aws s3 cp "$out_file" "$s3_daily"; then
        log "Uploaded to $s3_daily"
    else
        log "S3 upload failed for $DB_NAME"
    fi

    if [ "$day_dir" = "01" ]; then
        s3_monthly="s3://${S3_BACKUP_BUCKET}/monthly/${APP_NAME}/${today}/${DB_NAME}.dump.enc"
        if aws s3 cp "$out_file" "$s3_monthly"; then
            log "Uploaded to $s3_monthly"
        else
            log "S3 monthly upload failed for $DB_NAME"
        fi
    fi
else
    log "S3_BACKUP_BUCKET not set — local backup only"
fi
