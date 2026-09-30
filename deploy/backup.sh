#!/bin/sh
# Full cluster backup; PostgreSQL, Temporal persistence and visibility share it.
set -eu

deploy_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
db_container=$(docker compose \
    --env-file "$deploy_dir/.env" \
    -f "$deploy_dir/compose.yaml" \
    -f "$deploy_dir/compose.research.yaml" \
    ps -q db)
if [ -z "$db_container" ]; then
    echo "Whisky database container is not running" >&2
    exit 1
fi
exec docker exec --user postgres "$db_container" pgbackrest \
    --stanza=whisky --repo1-bundle backup --type=full
