#!/bin/sh
# Explicit, repeatable schema step for the dedicated PostgreSQL cluster.
set -eu

: "${SQL_HOST:?set PostgreSQL host}"
: "${SQL_USER:?set PostgreSQL user}"
: "${SQL_PASSWORD:=}"
: "${SQL_PORT:=5432}"
export PGPASSWORD="$SQL_PASSWORD"

for store in temporal temporal_visibility; do
    case "$store" in
        temporal) schema=temporal ;;
        temporal_visibility) schema=visibility ;;
    esac
    exists=$(psql -X -v ON_ERROR_STOP=1 -h "$SQL_HOST" -p "$SQL_PORT" \
        -U "$SQL_USER" -d postgres -Atqc \
        "SELECT 1 FROM pg_database WHERE datname = '$store'")
    if [ "$exists" != 1 ]; then
        temporal-sql-tool --plugin postgres12 --ep "$SQL_HOST" -p "$SQL_PORT" \
            -u "$SQL_USER" --db "$store" create
    fi

    version_table=$(psql -X -v ON_ERROR_STOP=1 -h "$SQL_HOST" -p "$SQL_PORT" \
        -U "$SQL_USER" -d "$store" -Atqc \
        "SELECT to_regclass('public.schema_version')")
    if [ "$version_table" != schema_version ]; then
        temporal-sql-tool --plugin postgres12 --ep "$SQL_HOST" -p "$SQL_PORT" \
            -u "$SQL_USER" --db "$store" setup-schema -v 0.0
    fi
    temporal-sql-tool --plugin postgres12 --ep "$SQL_HOST" -p "$SQL_PORT" \
        -u "$SQL_USER" --db "$store" update-schema \
        -d "/etc/temporal/schema/postgresql/v12/$schema/versioned"
done
