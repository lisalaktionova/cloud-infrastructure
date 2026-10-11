# Lab 6 - Репликация базы данных

PostgreSQL с потоковой репликацией, сервис с read/write splitting, replication lag, ручной failover и мониторинг.

## Что это

Продолжение Лабы 1. База данных из архитектуры «Пальчики оближешь» - та самая, что живёт в data-подсети. Здесь мы её поднимаем:

- **PostgreSQL с потоковой репликацией** - primary + standby через streaming replication.
- **Сервис с read/write splitting** - запись идёт в primary, чтение - со standby.
- **Replication lag** - замер и демонстрация отставания реплики.
- **Failover** - ручное повышение standby при отказе primary.
- **Мониторинг** - postgres-exporter + Prometheus + Grafana + Alertmanager.

Всё развёрнуто через Docker Compose на домашнем сервере, сервисы общаются через общую Docker-сеть `monitoring-net`.

Подробное описание каждой части и обоснование алертов - в [report.md](report.md).

## Что поднято

| Компонент | Роль | Порт |
|-----------|------|------|
| postgres-primary | Основной узел PostgreSQL (write + read) | 15432 |
| postgres-standby | Реплика (read-only) | 15433 |
| app | Сервис на FastAPI с read/write splitting | 8000 |
| postgres-exporter | Экспортёр метрик PostgreSQL | 9187 |
| Prometheus | Сбор метрик | 9090 |
| Grafana | Визуализация метрик | 3000 |
| Alertmanager | Рассылка алертов | 9093 |
| Loki | Хранилище логов | 3100 |
| Promtail | Агент сбора логов | 9080 |
| node-exporter | Метрики хоста | 9100 |

## Как это работает

```
postgres-primary (write + read)
        │
        │ streaming replication (WAL по TCP)
        ▼
postgres-standby (read-only)
        │
        ▼
app (FastAPI): write → primary, read → standby
```

1. Приложение пишет в **primary** через `POST /api/orders`.
2. Primary фиксирует запись в WAL.
3. Standby получает WAL по сети и применяет к своей копии данных.
4. Приложение читает со **standby** через `GET /api/orders`.
5. Пока WAL не догнал - standby возвращает устаревшие данные (replication lag).

## Что делает app

Мини-сервис на FastAPI с read/write splitting:

| Эндпоинт | Что делает | Куда идёт |
|----------|-----------|-----------|
| `GET /` | HTML-страница с кнопками | - |
| `POST /api/orders` | Создать запись | **primary** (write) |
| `GET /api/orders` | Список записей | **standby** (read) |
| `POST /api/load?count=N` | Налить нагрузку (N записей) | **primary** (write) |
| `GET /health` | Health check | - |

Адреса primary и standby вынесены в env: `PRIMARY_DSN`, `STANDBY_DSN`.

## Структура репозитория

```
lab-6/
├── README.md
├── docker-compose.yml
├── app/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── postgres/
│   ├── primary/
│   │   └── init-replication.sh
│   └── standby/
│       └── entrypoint.sh
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── alertmanager/
│   └── alertmanager.yml
├── loki/
│   └── loki-config.yml
├── promtail/
│   └── promtail-config.yml
└── screenshots/
    ├── WAL.png
    ├── test-standby.png
    ├── shop-app.png
    ├── replay_lag.png
    ├── promotion.png
    ├── grafana.png
    ├── error.png
    ├── alerts.png
    └── after-failover.png
```

## Как запустить

```bash
# 1. Общая сеть (один раз)
docker network create monitoring-net

# 2. Запуск
cd lab-6
docker compose up -d --build

# 3. Проверка
docker compose ps
```

При первом запуске standby сам сделает `pg_basebackup` с primary и подключится как реплика. В логах standby должно появиться `started streaming WAL from primary`.

## Подключение к серверу

```bash
ssh -L 18000:localhost:8000 \
    -L 15432:localhost:15432 \
    -L 15433:localhost:15433 \
    -L 19187:localhost:9187 \
    -L 19090:localhost:9090 \
    -L 13000:localhost:3000 \
    -L 19093:localhost:9093 \
    -L 19100:localhost:9100 \
    -L 13100:localhost:3100 \
    prj@cloud-infrastructure.yetti
```


## Скриншоты

- [`screenshots/WAL.png`](screenshots/WAL.png) - логи standby: `started streaming WAL from primary`
- [`screenshots/test-standby.png`](screenshots/test-standby.png) - запись в primary, чтение со standby, ошибка записи в standby
- [`screenshots/shop-app.png`](screenshots/shop-app.png) - страница app со списком записей
- [`screenshots/replay_lag.png`](screenshots/replay_lag.png) - replication lag из `pg_stat_replication`
- [`screenshots/promotion.png`](screenshots/promotion.png) - промоушен standby до primary
- [`screenshots/grafana.png`](screenshots/grafana.png) - дашборд Grafana с метриками репликации
- [`screenshots/error.png`](screenshots/error.png) - ошибка записи, когда primary упал
- [`screenshots/alerts.png`](screenshots/alerts.png) - алерт в Firing
- [`screenshots/after-failover.png`](screenshots/after-failover.png) - app после failover: запись снова работает