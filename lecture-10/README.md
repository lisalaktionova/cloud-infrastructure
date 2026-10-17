# Lab 10 - Внутренний GitLab

Развертывание и защита платформы разработки: единый вход (SSO), защита периметра (nginx) и CI/CD с эфемерными раннерами.

Подробное описание каждой части и обоснование алертов - в [report.md](report.md).

## Что это

Продолжение Лабы 1. Настроен центр разработки для сервиса «Пальчики оближешь»:

- GitLab CE и Keycloak (единый вход по OIDC) в Docker Compose.
- Внешний nginx с TLS-терминацией и правилами ограничения доступа.
- CI/CD пайплайн со статическим и эфемерным раннерами.
- Мониторинг GitLab через Prometheus и Grafana.

Всё развёрнуто через Docker Compose на домашнем сервере (LXC), сервисы общаются через общую Docker-сеть `monitoring-net`.

## Что поднято

| Компонент | Роль | Домен / Порт |
|-----------|------|--------------|
| gitlab | Платформа разработки (код, CI/CD, registry) | sso.local (443) |
| keycloak | Identity Provider (SSO, OIDC) | keycloak.local:18080 |
| grafana-lab10 | Визуализация метрик | grafana.local (443) |
| nginx-edge | Внешний reverse proxy и защита | 80 / 443 |
| gitlab-runner-static | Статический раннер (docker executor) | - |
| gitlab-runner-dynamic | Эфемерный раннер (docker executor) | - |
| prometheus | Сбор метрик | prometheus.local (443) |
| alertmanager | Маршрутизация алертов | 9093 |


## Структура репозитория

```text
lab10/
├── README.md
├── report.md
├── docker-compose.yml
├── alertmanager/
│   └── alertmanager.yml
├── gitlab-runner-dynamic/
│   └── config.toml
├── gitlab-runner-static/
│   └── config.toml
├── nginx/
│   ├── certs/
│   │   ├── server.crt
│   │   └── server.key
│   ├── gitlab.conf
│   └── proxy_params_gitlab.conf
├── prometheus/
│   ├── alerts.yml
│   └── prometheus.yml
└── screenshots/
    ├── admin403.png
    ├── health403.png
    ├── build-and-push.png
    ├── gitlab-keycloak-1.png
    ├── gitlab-keycloak-2.png
    ├── grafana-keycloak-1.png
    ├── grafana-keycloak-2.png
    ├── grafana.png
    ├── job-container.png
    ├── keycloak.png
    ├── pipeline.png
    ├── prometheus-1.png
    ├── prometheus-2.png
    ├── registry.png
    └── сертификат.png
```

## Как запустить

```bash
docker network create monitoring-net   # один раз
cd lab10
docker compose up -d --build
docker compose ps
```

Первый запуск GitLab занимает 5-7 минут.

## Подключение к серверу

```bash
ssh -L 80:localhost:80 \
    -L 443:localhost:443 \
    -L 18080:localhost:18080 \
    -L 2222:localhost:2222 \
    -L 5000:localhost:5000 \
    -L 19090:localhost:9090 \
    -L 13001:localhost:3001 \
    -o ServerAliveInterval=30 \
    prj@cloud-infrastructure.yetti
```

| Сервис | Адрес |
|--------|-------|
| GitLab | https://sso.local |
| Grafana | https://grafana.local |
| Keycloak | http://keycloak.local:18080 |
| Prometheus | http://prometheus.local |


## Скриншоты

### Часть 1. Единый вход (Keycloak)

Добавление тестового пользователя:

![Keycloak](screenshots/keycloak.png)

Кнопка Keycloak на странице входа GitLab:

![GitLab Keycloak 1](screenshots/gitlab-keycloak-1.png)

Успешный вход в GitLab под testuser:

![GitLab Keycloak 2](screenshots/gitlab-keycloak-2.png)

Кнопка Keycloak на странице входа Grafana:

![Grafana Keycloak 1](screenshots/grafana-keycloak-1.png)

Успешный вход в Grafana под testuser:

![Grafana Keycloak 2](screenshots/grafana-keycloak-2.png)

### Часть 2. nginx как рубеж защиты

Самоподписанный сертификат:

![Сертификат](screenshots/сертификат.png)

Запрет доступа к `/admin` снаружи (403 Forbidden):

![Admin 403](screenshots/admin403.png)

Запрет доступа к служебному `/health` (403 Forbidden):

![Health 403](screenshots/health403.png)

### Часть 3. CI/CD и раннеры

Успешный пайплайн (все стадии):

![Pipeline](screenshots/pipeline.png)

Логи сборки и пуша образа:

![Build and push](screenshots/build-and-push.png)

Эфемерный контейнер раннера под задачу:

![Job container](screenshots/job-container.png)

Образ, запушенный в Registry:

![Registry](screenshots/registry.png)

### Часть 4. Мониторинг GitLab

Targets в Prometheus (все джобы UP):

![Prometheus 1](screenshots/prometheus-1.png)

Алерты в Prometheus:

![Prometheus 2](screenshots/prometheus-2.png)

Дашборд Grafana с метриками GitLab:

![Grafana](screenshots/grafana.png)