# Lab 6 - Репликация базы данных

Поднятие PostgreSQL с потоковой репликацией (streaming replication), сервис с read/write splitting, ловля replication lag, ручной failover и мониторинг репликации.

## Что это

Продолжение Лабы 1. В архитектуре «Пальчики оближешь» есть база данных - та самая, что живёт в data-подсети и не смотрит в интернет. Здесь мы её поднимаем:

- PostgreSQL с потоковой репликацией - primary + standby через streaming replication.
- Сервис с read/write splitting - запись идёт в primary, чтение - со standby.
- Replication lag - замер и демонстрация отставания реплики.
- Failover - ручное повышение standby при отказе primary.
- Мониторинг - postgres-exporter + Prometheus + Grafana + Alertmanager.

Всё развёрнуто через Docker Compose на домашнем сервере, сервисы общаются через общую Docker-сеть `monitoring-net`.

## Выбор СУБД - PostgreSQL

Из двух вариантов (PostgreSQL / MongoDB) выбрана PostgreSQL. Причины:

1. Ручная репликация - больше контроля и понимания процесса. В MongoDB failover автоматический (elections), и не видно деталей.
2. Streaming replication - классический механизм, применимый во многих системах.
3. Ручной failover - можно показать, что происходит при отказе primary, шаг за шагом.
4. Опыт работы - в Лабе 1 PostgreSQL уже фигурировал как основная БД проекта.

## Что поднято

| Компонент | Роль | Порт |
|-----------|------|------|
| postgres-primary | Основной узел PostgreSQL (write + read) | 15432 |
| postgres-standby | Реплика (read-only) | 15433 |
| app | Сервис на FastAPI с read/write splitting | 8000 |
| postgres-exporter | Экспортёр метрик PostgreSQL для Prometheus | 9187 |
| Prometheus | Сбор метрик | 9090 |
| Grafana | Визуализация метрик | 3000 |
| Alertmanager | Рассылка алертов | 9093 |
| Loki | Хранилище логов | 3100 |
| Promtail | Агент сбора логов с Docker-контейнеров | 9080 |
| node-exporter | Метрики хоста (CPU, память, диск) | 9100 |

## Как это работает
Поток данных:

1. Приложение пишет в primary через `POST /api/orders`.
2. Primary фиксирует запись в WAL (write-ahead log).
3. Standby получает WAL по сети и применяет к своей копии данных.
4. Приложение читает со standby через `GET /api/orders`.
5. Пока WAL не догнал - standby возвращает устаревшие данные (replication lag).

## Что делает app

Мини-сервис на FastAPI с read/write splitting:

| Эндпоинт | Что делает | Куда идёт |
|----------|-----------|-----------|
| `GET /` | HTML-страница с кнопками | - |
| `POST /api/orders` | Создать запись | primary (write) |
| `GET /api/orders` | Список записей | standby (read) |
| `POST /api/load?count=N` | Налить нагрузку (N записей) | primary (write) |
| `GET /health` | Health check | - |

Конфигурация через env:

| Переменная | Что задаёт |
|-----------|-----------|
| `PRIMARY_DSN` | DSN primary (`postgresql://appuser:***@postgres-primary:5432/shopdb`) |
| `STANDBY_DSN` | DSN standby (`postgresql://appuser:***@postgres-standby:5432/shopdb`) |

## Часть 1. Репликация через конфигурацию

### Как поднято

Primary. Параметры в `docker-compose.yml`:

```yaml
command: ["postgres", "-c", "wal_level=replica", "-c", "max_wal_senders=5", "-c", "max_replication_slots=5", "-c", "hot_standby=on", "-c", "listen_addresses=*"]
```

- `wal_level=replica` - PostgreSQL пишет достаточно WAL для репликации.
- `max_wal_senders=5` - сколько standby могут одновременно подключиться.
- `hot_standby=on` - standby доступен для чтения.

Standby. При первом запуске запускается скрипт `postgres/standby/entrypoint.sh`:

1. Ждёт готовности primary через `pg_isready`.
2. Делает базовую копию: `pg_basebackup -h postgres-primary -U repluser -D /var/lib/postgresql/data -Fp -Xs -R -P`.
3. Флаг `-R` создаёт `standby.signal` и прописывает `primary_conninfo` в `postgresql.auto.conf`.
4. Запускает `postgres` в режиме standby.

Скрипт `postgres/primary/init-replication.sh` создаёт роль `repluser` с правом `REPLICATION` и добавляет правила в `pg_hba.conf`.

### Что наблюдали

- В логах standby: `Data directory empty, running pg_basebackup from primary...` -> `pg_basebackup completed.`  -> `LOG: entering standby mode`  -> `LOG: started streaming WAL from primary`.
- Запись в primary видна на standby.
- Запись напрямую в standby падает с ошибкой `cannot execute INSERT in a read-only transaction`.
- `pg_stat_replication` на primary показывает `state = streaming`.

## Часть 2. Сервис с read/write splitting

- Запись (`POST /api/orders`, `POST /api/load`)  -> primary.
- Чтение (`GET /api/orders`)  -> standby.

## Часть 3. Replication lag

### Что делали

1. Запустили непрерывную нагрузку через `POST /api/load?count=1000` в цикле.
2. Одновременно замеряли lag через `pg_stat_replication` на primary.

### Что замерили

```
 lag_bytes |   replay_lag
-----------+-----------------
         0 | 00:00:00.008242
```

Lag = 8 миллисекунд.

### Почему lag такой маленький

В учебной среде primary и standby живут в одной Docker-сети на одном сервере:

- Сетевая задержка между контейнерами - микросекунды.
- Диск - быстрый (SSD).
- Нагрузка - простые INSERT'ы, применяются мгновенно.

Поэтому lag измеряется миллисекундами.

### Чем это грозит

Проблема read-your-own-writes: пользователь записал данные в primary, сразу прочитал со standby - не увидел.

### Как измеряли

Основной способ - `pg_stat_replication` на primary:

```sql
SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes,
       replay_lag
FROM pg_stat_replication;
```

## Часть 4. Теорема CAP

### К чему тяготеет наша настройка - к A (Availability)

Мы используем асинхронную streaming replication:

- Primary записал данные и сразу ответил клиенту «готово».
- Standby получает WAL асинхронно - с задержкой.
- Чтение со standby не блокируется, даже если реплика отстала.

Это AP-система: всегда доступна, но может давать устаревшие данные.

### Что нужно поменять, чтобы сместиться в C

Включить синхронную репликацию на primary:

```yaml
command: ["postgres",
  "-c", "synchronous_commit=on",
  "-c", "synchronous_standby_names=*", ...]
```

Тогда primary будет ждать подтверждения от standby, прежде чем ответить клиенту «записано». Чтение со standby всегда будет актуальным.

### Цена за C

- Запись замедляется - на время сетевой задержки между primary и standby.
- Если standby недоступен - записи на primary падают (primary не может подтвердить commit без standby).

### Вывод

CAP-теорема на практике - выбор между:

- AP - «всегда отвечает, но может давать устаревшие данные».
- CP - «данные всегда актуальны, но система может быть недоступна».

Наша конфигурация - AP.

## Часть 5. Failover

### Что делали

1. Остановили primary: `docker compose stop postgres-primary`.
2. Попробовали создать запись через app  -> ошибка 500 (`connection refused`).
3. Попробовали прочитать со standby  -> работает (ключевой момент).
4. Повысили standby до primary: `pg_ctl promote`.
5. Переключили app на нового primary.
6. Запись снова заработала.

### Что было бы, если бы старый primary вернулся

Split-brain - два primary, данные расходятся. У старого primary в WAL есть записи, которых нет на новом primary, и наоборот.

Автоматически ничего не разрешается. В PostgreSQL нет встроенного механизма для разрешения такого конфликта.

Чтобы вернуть старый primary в строй:

1. Остановить его.
2. Удалить его данные.
3. Сделать `pg_basebackup` с нового primary - то есть заново подключить как standby.

### Как это автоматизируют в проде

- Patroni - управляет кластером, сам повышает standby при отказе, предотвращает split-brain.
- Stolon - альтернатива.
- AWS RDS Multi-AZ - managed-решение.

В нашем случае failover был ручной.

## Часть 6. Мониторинг

Для сбора метрик PostgreSQL используется postgres-exporter. Prometheus скрейпит его каждые 15 секунд. Grafana показывает метрики на дашборде.

### Дашборд

Дашборд `PostgreSQL replication - Lab 6` включает 3 панели:

| Панель | Запрос | Что показывает |
|--------|--------|----------------|
| PostgreSQL up | `pg_up{job="postgres-exporter"}` | 1 - exporter подключился к БД, 0 - нет |
| Connected standbys | `count(pg_stat_replication_pg_wal_lsn_diff{state="streaming"}) or vector(0)` | Сколько standby подключено |
| Replication lag | `pg_stat_replication_pg_wal_lsn_diff{state="streaming"} or vector(0)` | Отставание в байтах |

Про `or vector(0)`: когда standby отключается, метрика `pg_stat_replication_pg_wal_lsn_diff` перестаёт отдаваться экспортёром. Prometheus обрывает временной ряд, и Grafana показывает «No data» вместо 0. Мы решили это через `or vector(0)` - если метрика отсутствует, возвращается 0.

### Три алерта

1. PostgresDown

```promql
pg_up{job="postgres-exporter"} == 0
```

Что ловит: postgres-exporter не может подключиться к БД больше 1 минуты.

Чем грозит: вся система теряет доступ к БД - ни чтения, ни записи. Критичный инцидент, требует немедленного вмешательства.

Почему эта метрика: базовый health-check. Без работающего primary вся система стоит.

2. StandbyDisconnected

```promql
absent(pg_stat_replication_pg_wal_lsn_diff{state="streaming"})
```

Что ловит: ни один standby не стримит WAL с primary больше 2 минут.

Чем грозит: критичный инцидент. Запись продолжает работать (primary жив), но чтение падает - app читает со standby, а он недоступен. Пользователи видят ошибки вместо списка записей. Резерва нет: если primary упадёт, данные потеряются полностью, failover сделать некуда. Когда standby вернётся, ему придётся догонять весь объём WAL, накопившийся за время отключения.

Почему эта метрика: наличие реплики - фундамент отказоустойчивости.

Почему `absent()`: правило срабатывает, когда метрика исчезла.

3. ReplicationLagHigh

```promql
pg_stat_replication_pg_wal_lsn_diff{state="streaming"} > 104857600
```

Порог - 100 МБ (`104857600` байт).

Что ловит: lag превышает 100 МБ в течение 2 минут.

Чем грозит: чтение со standby возвращает устаревшие данные. При failover standby не знает о свежих записях. Чем больше lag - тем дольше догонять.

Почему 100 МБ: сигнал разобраться. В реальной системе порог подбирают под SLO - например, «lag не должен превышать 5 секунд».

## Скриншоты

- [`screenshots/WAL.png`](screenshots/WAL.png) - логи standby: `started streaming WAL from primary`
- [`screenshots/test-standby.png`](screenshots/test-standby.png) - запись в primary, чтение со standby, ошибка записи в standby (read-only)
- [`screenshots/shop-app.png`](screenshots/shop-app.png) - страница app со списком записей
- [`screenshots/replay_lag.png`](screenshots/replay_lag.png) - replication lag из `pg_stat_replication`
- [`screenshots/promotion.png`](screenshots/promotion.png) - промоушен standby до primary
- [`screenshots/grafana.png`](screenshots/grafana.png) - дашборд Grafana с метриками репликации
- [`screenshots/error.png`](screenshots/error.png) - ошибка записи, когда primary упал
- [`screenshots/alerts.png`](screenshots/alerts.png) - алерт в Firing
- [`screenshots/after-failover.png`](screenshots/after-failover.png) - app после failover: запись снова работает

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

| Сервис | Адрес |
|--------|-------|
| app | http://127.0.0.1:18000 |
| PostgreSQL primary | localhost:15432 |
| PostgreSQL standby | localhost:15433 |
| postgres-exporter | http://127.0.0.1:19187 |
| Prometheus | http://127.0.0.1:19090 |
| Grafana | http://127.0.0.1:13000 (admin/admin) |
| Alertmanager | http://127.0.0.1:19093 |

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