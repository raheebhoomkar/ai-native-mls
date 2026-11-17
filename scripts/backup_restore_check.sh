#!/usr/bin/env bash
# Proves a backup can be restored: backs up DATABASE_URL, restores it into a scratch
# database on the same server, and compares the row count of every table.
#
#   DATABASE_URL=postgresql://user:pass@host:5432/mls scripts/backup_restore_check.sh
#
# The scratch database (<name>_restore_check) is dropped and created on each run.
set -euo pipefail
source "$(dirname "$0")/pg.sh"

source_url="$(plain_url "${DATABASE_URL:?Set DATABASE_URL to the database to check.}")"
base="${source_url%%\?*}"
name="${base##*/}"
scratch_name="${name}_restore_check"
scratch_url="${base%/*}/$scratch_name"
dump="$(mktemp -t mls-restore-check.XXXXXX)"
trap 'rm -f "$dump" "$dump".*' EXIT

# Every table in the public schema with its row count, one "table count" line each.
counts() {
  pg psql --no-psqlrc --quiet --tuples-only --no-align --field-separator=' ' \
    --dbname="$1" --command="
    SELECT table_name,
           (xpath('/row/c/text()',
                  query_to_xml(format('SELECT count(*) AS c FROM %I', table_name),
                               false, true, '')))[1]::text
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name"
}

pg psql --no-psqlrc --quiet --dbname="$source_url" \
  --command="SET client_min_messages TO warning" \
  --command="DROP DATABASE IF EXISTS \"$scratch_name\"" \
  --command="CREATE DATABASE \"$scratch_name\""

"$(dirname "$0")/backup.sh" "$dump.dump" >/dev/null
"$(dirname "$0")/restore.sh" "$dump.dump" "$scratch_url" >/dev/null

counts "$source_url" > "$dump.source"
counts "$scratch_url" > "$dump.restored"
pg psql --no-psqlrc --quiet --dbname="$source_url" --command="DROP DATABASE \"$scratch_name\""

if ! diff "$dump.source" "$dump.restored"; then
  echo "Restore check FAILED: row counts differ (left: original, right: restored)." >&2
  exit 1
fi
echo "Restore check passed: $(wc -l < "$dump.source" | tr -d ' ') tables, same row counts."
