#!/usr/bin/env bash
# Back up the database to one file in pg_dump's custom format.
#
#   DATABASE_URL=postgresql://user:pass@host:5432/mls scripts/backup.sh [out-file]
#
# Default file: var/backups/mls-<UTC time>.dump. Prints the file path.
set -euo pipefail
source "$(dirname "$0")/pg.sh"

url="$(plain_url "${DATABASE_URL:?Set DATABASE_URL to the database to back up.}")"
out="${1:-var/backups/mls-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p "$(dirname "$out")"

pg pg_dump --format=custom --no-owner --no-privileges --dbname="$url" > "$out.partial"
mv "$out.partial" "$out"  # a failed dump never leaves a file that looks complete
echo "$out"
