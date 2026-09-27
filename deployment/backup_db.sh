#!/usr/bin/env bash
# Humatron Automated PostgreSQL Backup Script (Section 69)
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/humatron/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_NAME="${DB_NAME:-humatron_db}"
DB_USER="${DB_USER:-humatron_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

mkdir -p "${BACKUP_DIR}"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump"
LOG_FILE="${BACKUP_DIR}/backup.log"

echo "[$(date)] Starting backup of database '${DB_NAME}'..." >> "${LOG_FILE}"

# Execute custom-format compressed backup
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -F c -b -v -f "${BACKUP_FILE}" "${DB_NAME}" 2>> "${LOG_FILE}"

# Generate SHA256 checksum
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"

# Verify backup integrity
pg_restore -l "${BACKUP_FILE}" > /dev/null

echo "[$(date)] Backup completed successfully: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))" >> "${LOG_FILE}"

# Rotate old backups
find "${BACKUP_DIR}" -name "${DB_NAME}_*.dump" -mtime +"${RETENTION_DAYS}" -delete
find "${BACKUP_DIR}" -name "${DB_NAME}_*.dump.sha256" -mtime +"${RETENTION_DAYS}" -delete

echo "[$(date)] Backup rotation completed. Retained last ${RETENTION_DAYS} days." >> "${LOG_FILE}"
