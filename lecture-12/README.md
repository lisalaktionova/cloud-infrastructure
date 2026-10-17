# Lab 12 - AI-ассистент поддержки на n8n

Автоматизация обработки тикетов с помощью AI-агента, MCP-серверов и n8n.

Подробное описание кейса и архитектуры - в [report.md](report.md).

## Что это

Продолжение Лабы 1. Настроен ассистент нулевой линии поддержки для сервиса «Пальчики оближешь»:

- AI-агент обрабатывает типовые вопросы клиентов (статус заказа, FAQ).
- Доступ к данным реализован через MCP-серверы Filesystem и Fetch.
- Сложные вопросы (возврат денег, юридические) эскалируются на операторов.
- Настроен мониторинг нагрузки и ошибок workflow через Prometheus и Grafana.

## Что поднято

| Компонент | Роль | Порт |
|-----------|------|------|
| n8n | Платформа автоматизации и AI-агент | 5678 |
| mock-logistics | Мок-сервис статусов доставки | 8080 |
| mcp-filesystem | MCP-сервер доступа к файлам | 8000 |
| mcp-fetch | MCP-сервер HTTP-запросов | 8001 |
| Prometheus | Сбор метрик | 9090 |
| Grafana | Визуализация | 3002 |

## Как это работает

1. Система тикетов отправляет POST-запрос на Webhook n8n.
2. AI-агент читает заказ и FAQ через MCP Filesystem, запрашивает статус доставки через MCP Fetch.
3. Если вопрос решаем, агент генерирует ответ и сохраняет его в файл через MCP Filesystem.
4. Если вопрос про деньги или юриспруденцию, создается файл эскалации.

## Структура репозитория

```text
lab-12/
├── README.md
├── report.md
├── docker-compose.yml
├── data/
│   ├── orders.json
│   └── faq.json
├── responses/
├── escalations/
├── mock-logistics/
│   ├── Dockerfile
│   └── mock_logistics.py
├── prometheus/
│   ├── alerts.yml
│   └── prometheus.yml
└── screenshots/
    ├── ai-working.png
    ├── grafana.png
    ├── n8n-account.png
    ├── prometheus-1.png
    ├── prometheus-2.png
    └── scheme.png
```

## Как запустить

```bash
docker network create monitoring-net   # один раз
cd lab-12
docker compose up -d --build
docker compose ps
```

## Подключение к серверу

```bash
ssh -L 5678:localhost:5678 \
    -L 3002:localhost:3002 \
    -L 9090:localhost:9090 \
    prj@cloud-infrastructure.yetti
```

| Сервис | Адрес |
|--------|-------|
| n8n | http://127.0.0.1:5678 |
| Grafana | http://127.0.0.1:3002 (admin/admin) |
| Prometheus | http://127.0.0.1:9090 |


## Скриншоты

Схема workflow:
![Scheme](screenshots/scheme.png)

Создание аккаунта в n8n:
![N8n Account](screenshots/n8n-account.png)

Работа AI-агента:
![AI Working](screenshots/ai-working.png)

Targets в Prometheus:
![Prometheus 1](screenshots/prometheus-1.png)

Алерты в Prometheus:
![Prometheus 2](screenshots/prometheus-2.png)

Дашборд Grafana:
![Grafana](screenshots/grafana.png)