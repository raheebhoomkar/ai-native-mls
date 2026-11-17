#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into the database you name.
#
#   scripts/restore.sh <dump-file> <target-database-url>
#
# This REPLACES the tables in the target database with those in the backup.
# The target database must exist. It is never taken from DATABASE_URL, so a
# restore cannot hit the running app's database by accident.
set -euo pipefail
source "$(dirname "$0")/pg.sh"

dump="${1:?Usage: scripts/restore.sh <dump-file> <target-database-url>}"
target="$(plain_url "${2:?Usage: scripts/restore.sh <dump-file> <target-database-url>}")"
[ -s "$dump" ] || { echo "No backup at $dump" >&2; exit 1; }

pg pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error \
  --dbname="$target" < "$dump"
echo "Restored $dump"
