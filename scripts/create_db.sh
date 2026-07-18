#!/usr/bin/env bash
# One-time bootstrap: creates the empty MySQL/MariaDB database that Django's
# migrations then own entirely. Safe to re-run (CREATE DATABASE IF NOT EXISTS).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -f .env ]; then
    echo "error: .env not found in project root" >&2
    exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

: "${DB_NAME:?DB_NAME not set in .env}"
: "${DB_USER:?DB_USER not set in .env}"
: "${DB_PASSWORD:?DB_PASSWORD not set in .env}"
: "${DB_HOST:=localhost}"
: "${DB_PORT:=3306}"

mysql \
    -u "$DB_USER" \
    -p"$DB_PASSWORD" \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

echo "Database '${DB_NAME}' ready. Run 'python manage.py migrate' next."
