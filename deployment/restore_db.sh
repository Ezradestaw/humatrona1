#!/usr/bin/env bash
# Humatron Database Restoration Script (Section 69)
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path_to_backup_file.dump>"
    exit 1
fi

BACKUP_FILE="$1"
DB_NAME="${DB_NAME:-humatron_db}"
DB_USER="${DB_USER:-humatron_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Error: File '${BACKUP_FILE}' does not exist."
    exit 1
fi

# Verify checksum if present
if [ -f "${BACKUP_FILE}.sha256" ]; then
    echo "Verifying checksum..."
    sha256sum -c "${BACKUP_FILE}.sha256"
fi

echo "Warning: This will restore into database '${DB_NAME}' on ${DB_HOST}:${DB_PORT}."
read -p "Type 'RESTORE' to proceed: " CONFIRMATION

if [ "${CONFIRMATION}" != "RESTORE" ]; then
    echo "Restoration aborted."
    exit 1
fi

echo "Starting restoration..."
pg_restore -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists -v "${BACKUP_FILE}"
echo "Restoration completed successfully."
