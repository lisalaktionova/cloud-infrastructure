# Lab 8 - ELK и работа с Elasticsearch

Поднятие Elasticsearch + Kibana, заливка логов, поиск и агрегация, ILM + rollover, мониторинг кластера.

## Что это

- Elasticsearch 8.x + Kibana в Docker Compose.
- Индекс с явным маппингом для логов приложения.
- 30 реалистичных логов по предметной области «Пальчики оближешь» через Bulk API.
- Поиски: полнотекстовый, по уровню, по trace_id. Агрегации по level и service.
- ILM + rollover для автоматического управления индексами.
- Мониторинг Elasticsearch через elasticsearch-exporter + Prometheus + Grafana.

Всё развёрнуто через Docker Compose на домашнем сервере, сервисы общаются через общую Docker-сеть `monitoring-net`.

## Что поднято

| Компонент | Роль | Порт |
|-----------|------|------|
| elasticsearch | Хранилище логов и поисковый движок | 9200 |
| kibana | UI для поиска и визуализации | 5601 |
| elasticsearch-exporter | Метрики ES для Prometheus | 9114 |
| Prometheus | Сбор метрик | 9090 |
| Grafana | Визуализация метрик | 3000 |
| Alertmanager | Рассылка алертов | 9093 |

## Как это работает

```text
logs.json  ->  Bulk API  ->  Elasticsearch (shop-logs)  ->  Kibana
```

1. Генерируем 30 реалистичных логов по предметной области (сервисы frontend, api, db, logistics, payment, backup; уровни INFO, WARN, ERROR).
2. Создаём индекс `shop-logs` с явным маппингом: timestamp (date), level/service/trace_id (keyword), message (text).
3. Заливаем через Bulk API.
4. Ищем и агрегируем через Kibana или REST API.
5. Настраиваем ILM + rollover - ES сам управляет индексами по мере роста.
6. Мониторим кластер через elasticsearch-exporter и Grafana.

## Часть 1. Развёртывание ELK

### Состояние кластера

Изначально кластер был yellow: Filebeat создал индекс `logs-app` с `number_of_replicas: 1`, а на одном узле реплику разместить некуда.

После удаления Filebeat и создания своих индексов с `number_of_replicas: 0` кластер стал green:

```json
GET _cluster/health

{
  "cluster_name" : "docker-cluster",
  "status" : "green",
  "number_of_nodes" : 1,
  "number_of_data_nodes" : 1,
  "active_primary_shards" : 15,
  "active_shards" : 15,
  "unassigned_shards" : 0,
  "active_shards_percent_as_number" : 100.0
}
```

### Почему статус green, а не yellow

Elasticsearch требует, чтобы реплика шарда находилась на другом узле, чем primary. На одном узле реплики разместить некуда.

Мы создаём индексы явно с `number_of_replicas: 0`. Реплик нет - значит, нечему быть нераспределённым, и кластер green.


### Что нужно для настоящего green с репликами

Минимум два узла (data-ноды). Тогда:

- Каждый primary-шард получит реплику на втором узле.
- При отказе одного узла реплика станет primary, статус останется green.
- Данные доступны даже при отказе одной ноды.

В production обычно 3 узла: обеспечивают отказоустойчивость и кворум для выборов master-ноды.

## Часть 2. Данные, индекс и поиск

### Маппинг индекса

```json
PUT shop-logs
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0
  },
  "mappings": {
    "properties": {
      "timestamp": { "type": "date" },
      "level":     { "type": "keyword" },
      "service":   { "type": "keyword" },
      "message":   { "type": "text" },
      "trace_id":  { "type": "keyword" }
    }
  }
}
```

- `timestamp` - date - фильтрация по диапазонам.
- `level`, `service`, `trace_id` - keyword - точное совпадение и агрегации.
- `message` - text - полнотекстовый поиск.
- `number_of_replicas: 0` - чтобы индекс был green на одном узле.

### Логи

30 записей: 20 INFO, 5 WARN, 5 ERROR. Сервисы: frontend, api, db, logistics, payment, backup. Разные trace_id, некоторые повторяются (события одного заказа).

Залили через Bulk API.

### Поиски

Полнотекстовый:

```json
GET shop-logs/_search
{ "query": { "match": { "message": "payment" } } }
```

Фильтр по level + диапазон:

```json
GET shop-logs/_search
{
  "query": {
    "bool": {
      "must": [
        { "term": { "level": "ERROR" } },
        { "range": { "timestamp": { "gte": "2026-10-11T09:00:00Z", "lte": "2026-10-11T09:30:00Z" } } }
      ]
    }
  }
}
```

По trace_id:

```json
GET shop-logs/_search
{ "query": { "term": { "trace_id": "a1b2c3d4e5f60001" } } }
```

### Агрегация

```json
GET shop-logs/_search
{ "size": 0, "aggs": { "by_level": { "terms": { "field": "level" } } } }
```

Результат:

```text
INFO:  20
WARN:  5
ERROR: 5
```

### Визуализация в Kibana

Data View на индекс `shop-logs`, столбики по level.

## Часть 3. ILM + rollover

### Зачем ILM

Логи растут постоянно. Без управления индексами диск заполнится, поиск замедлится. ILM решает это автоматически.

### Политика

`shop-logs-policy`:

- Hot: rollover при 5 МБ или 1 дне.
- Delete: удаление через 7 дней.

Для демо порог 5 МБ очень маленький. В production - 30-50 ГБ.

### Template и alias

- Index template `shop-logs-template` применяется ко всем `shop-logs-*` и подключает ILM.
- Alias `shop-logs-write` - точка записи. ES сам решает, в какой индекс писать.

### Rollover

```json
POST shop-logs-write/_rollover
{ "conditions": { "max_size": "1b" } }
```

ES создал `shop-logs-000002` и переключил alias:

```text
GET _cat/aliases/shop-logs-write?v

alias            index             is_write_index
shop-logs-write  shop-logs-000001  false
shop-logs-write  shop-logs-000002  true
```

### Список индексов после rollover

```text
GET _cat/indices/shop-logs*?v

green open shop-logs-000001   ...
green open shop-logs-000002   ...
```

Оба green - потому что `rep=0`.

### Почему префикс shop-logs, а не logs-shop

ES 8.x отказался создавать `logs-shop-000001`:

```text
cannot create index with name [logs-shop-000001], because it matches
with template [logs] that creates data streams only
```

В ES 8.x есть встроенные шаблоны `logs-*`, `metrics-*`, `traces-*`, которые создают data streams. Наш индекс попал под шаблон `logs-*`.

Решение: префикс `shop-logs-*`, который не конфликтует со встроенными шаблонами.

## Часть 4. Мониторинг

### Дашборд

| Панель | Запрос | Что показывает |
|--------|--------|----------------|
| Disk usage | `1 - (free_bytes / size_bytes)` | Процент занятого диска |
| JVM heap usage | `used_bytes / max_bytes` | Процент использования heap |
| Documents count | `elasticsearch_indices_docs` | Сколько документов |

### Три алерта

1. ElasticsearchClusterRed

```promql
elasticsearch_cluster_health_status{color="red"} == 1
```

Что ловит: кластер в статусе RED больше 1 минуты.

Чем грозит: часть primary-шардов недоступна. Данные потеряны или недоступны для поиска. Критичный инцидент.

2. ElasticsearchClusterYellow

```promql
elasticsearch_cluster_health_status{color="yellow"} == 1
```

Что ловит: кластер в статусе YELLOW больше 10 минут.

Чем грозит: реплики шардов нераспределены. Данные доступны, но нет резерва. Если узел с primary-шардом упадёт - данные потеряются.

Почему 10 минут: короткий YELLOW бывает при rebalance или создании индекса. 10 минут - устойчивая проблема.

3. ElasticsearchJVMHeapHigh

```promql
elasticsearch_jvm_memory_used_bytes / elasticsearch_jvm_memory_max_bytes > 0.85
```

Что ловит: heap использован более чем на 85% в течение 5 минут.

Чем грозит: активная сборка мусора, паузы в обработке, риск OutOfMemoryError и падения узла. Поиск и индексация замедляются.

Почему 85%: при 75% ES уже работает неоптимально, при 85% - риск. При 100% узел уже упал.

## Как запустить

```bash
docker network create monitoring-net   # один раз
cd lab-8
docker compose up -d --build
docker compose ps
```

Первый запуск - 1-2 минуты.

## Подключение к серверу

```bash
ssh -L 19090:localhost:9090 \
    -L 13000:localhost:3000 \
    -L 19093:localhost:9093 \
    -L 19200:localhost:9200 \
    -L 15601:localhost:5601 \
    -L 19114:localhost:9114 \
    prj@cloud-infrastructure.yetti
```

| Сервис | Адрес |
|--------|-------|
| Elasticsearch | http://127.0.0.1:19200 |
| Kibana | http://127.0.0.1:15601 |
| Prometheus | http://127.0.0.1:19090 |
| Grafana | http://127.0.0.1:13000 (admin/admin) |
| Alertmanager | http://127.0.0.1:19093 |

## Структура репозитория

```text
lab-8/
├── README.md
├── docker-compose.yml
├── logs.json
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── alertmanager/
│   └── alertmanager.yml
└── screenshots/
    ├── заливка.png
    ├── request-1.png
    ├── request-2.png
    ├── request-3.png
    ├── request-4.png
    ├── ilm.png
    ├── start-index.png
    ├── rollover.png
    ├── rollover-result.png
    ├── elastic-lens.png
    ├── grafana.png
    └── prometheus.png
```

## Скриншоты

### Часть 1. Развёртывание ELK

Изначально кластер был yellow (из-за Filebeat с rep=1):

![Status yellow](screenshots/status-yellow.png)

### Часть 2. Данные, индекс и поиск

Заливка логов:

![Bulk result](screenshots/заливка.png)

Полнотекстовый поиск:

![Request 1](screenshots/request-1.png)

Фильтр по level + диапазон:

![Request 2](screenshots/request-2.png)

Поиск по trace_id:

![Request 3](screenshots/request-3.png)

Агрегация по level:

![Request 4](screenshots/request-4.png)

### Часть 3. ILM + rollover

ILM-политика и template:

![ILM](screenshots/ilm.png)

Начальный индекс с alias:

![Start index](screenshots/start-index.png)

Rollover:

![Rollover](screenshots/rollover.png)

Результат rollover:

![Rollover result](screenshots/rollover-result.png)

### Часть 4. Мониторинг

Визуализация в Kibana:

![Elastic Lens](screenshots/elastic-lens.png)

Дашборд Grafana:

![Grafana](screenshots/grafana.png)

Алерты в Prometheus:

![Prometheus](screenshots/prometheus.png)

## Команды для справки

Проверить состояние кластера:

```bash
curl -s "http://localhost:9200/_cluster/health?pretty"
```

Список индексов:

```bash
curl -s "http://localhost:9200/_cat/indices?v"
```

Список шардов:

```bash
curl -s "http://localhost:9200/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason"
```

Проверить alias:

```bash
curl -s "http://localhost:9200/_cat/aliases/shop-logs-write?v"
```

Посчитать документы:

```bash
curl -s "http://localhost:9200/shop-logs/_count?pretty"
```

Метрики ES:

```bash
curl -s "http://localhost:9114/metrics" | grep elasticsearch_cluster_health_status
```