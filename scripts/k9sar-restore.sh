#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/k9sar-mysql"
DB_NAME="k9sar"
LOGIN_PATH="k9sar_backup"
RETENTION_DAYS=7

TIMESTAMP="$(date -u +%Y-%m-%d_%H-%M-%S)"
OUT_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}_utc.sql.gz"
TMP_FILE="${OUT_FILE}.tmp"

mkdir -p "${BACKUP_DIR}"

echo "Starting backup at ${TIMESTAMP} (UTC)..."

# Create backup to temp file first
mysqldump --login-path="${LOGIN_PATH}" \
  --single-transaction \
  --skip-lock-tables \
  --quick \
  --routines --triggers --events \
  --set-gtid-purged=OFF \
  --no-tablespaces \
  "${DB_NAME}" | gzip -1 > "${TMP_FILE}"

# Validate: the dump should start with a MySQL dump header
if ! gzip -cd "${TMP_FILE}" | head -n 5 | grep -q "MySQL dump"; then
  echo "ERROR: Backup validation failed (dump header not found)."
  echo "Keeping temp file for inspection: ${TMP_FILE}"
  exit 1
fi

mv -f "${TMP_FILE}" "${OUT_FILE}"
echo "Backup written to: ${OUT_FILE}"

# Retention cleanup
find "${BACKUP_DIR}" -type f -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "Old backups older than ${RETENTION_DAYS} days removed (if any)."
echo "Done."
