#!/usr/bin/env bash
# Run nightly via systemd timer or cron, e.g.:
#   0 2 * * * /opt/agaram_finance/deploy/backup.sh
set -euo pipefail

set -a; source /opt/agaram_finance/.env; set +a

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST_DIR="/var/backups/agaram_finance"
FILE="$DEST_DIR/agaram_finance_$TIMESTAMP.sql.gz"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$DEST_DIR"

pg_dump "$DATABASE_URL" | gzip > "$FILE"

# TODO: sync $FILE to off-site storage (S3 / another server) here, e.g.:
#   aws s3 cp "$FILE" s3://your-bucket/agaram-backups/

find "$DEST_DIR" -name '*.sql.gz' -mtime +"$RETENTION_DAYS" -delete

echo "Backup written to $FILE"
