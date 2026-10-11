#!/bin/bash
set -e

if [ ! -s /var/lib/postgresql/data/PG_VERSION ]; then
    echo "Data directory empty, running pg_basebackup from primary..."

    # Ждём, пока primary будет готов принимать соединения
    until PGPASSWORD=replpassword pg_isready -h postgres-primary -U repluser; do
        echo "Waiting for primary..."
        sleep 2
    done

    # Базовая копия + автоматическая настройка standby
    PGPASSWORD=replpassword pg_basebackup \
        -h postgres-primary \
        -U repluser \
        -D /var/lib/postgresql/data \
        -Fp -Xs -R -P

    chmod 0700 /var/lib/postgresql/data
    echo "pg_basebackup completed."
fi

# Запускаем postgres через стандартный entrypoint образа
exec docker-entrypoint.sh postgres