#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE repluser WITH REPLICATION LOGIN PASSWORD 'replpassword';
EOSQL

# Разрешаем подключения replication от любого контейнера docker-сети
echo "host replication repluser all scram-sha-256" >> "$PGDATA/pg_hba.conf"
echo "host all all all scram-sha-256" >> "$PGDATA/pg_hba.conf"

echo "Replication user 'repluser' created."