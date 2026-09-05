# BLACK ICE

Пайплайн контроля доступа по распознаванию лиц, стилизованный под ICE из
Cyberpunk 2077 — семантика defensive access-control в архитектуре, эстетика
netrunner-терминала в UI. Построен по полному роадмапу `BLACK_ICE_spec.md`:
монолит → message-driven сервисы → Kubernetes → observability →
security/compliance-усиление.

## Архитектура

```
ingest (1 pod/камера) --frames.raw--> detect (consumer group) --faces.detected--> embed (consumer group) --faces.embedded--> match (API + consumer)
                                          |                                                                                       |
                                    tracking lib (norfair)                                                          Qdrant (поиск) + Postgres (audit/identities)
```

Протокол Kafka через Redpanda (один бинарник, без Zookeeper — тот же клиентский
код `confluent-kafka`, что и для настоящего Kafka-кластера; в проде достаточно
поменять bootstrap-сервер). Смотри [services/](services) — по одному этапу на
сервис, [libs/black_ice_common](libs/black_ice_common) — общий код
детекции/эмбеддинга/трейсинга/RBAC, который импортирует каждый сервис.

### Почему детекция и эмбеддинг — разные сервисы

`FaceAnalysis.get()` требует загруженную модель детекции и всегда прогоняет
каждую модель из пака — как раз та связанность, которую этап 2 должен убрать,
чтобы CPU-bound детектор и (GPU-bound в проде) эмбеддер масштабировались
независимо. Оба вместо этого грузят свой единственный ONNX-файл напрямую через
`insightface.model_zoo`
([libs/black_ice_common/detection.py](libs/black_ice_common/detection.py),
[embedding.py](libs/black_ice_common/embedding.py)).

### Проблема GIL (спека, раздел 3.1)

Весь стек на Python, поэтому единица горизонтального масштабирования —
**процесс/под**, а не поток: ingest — один OS-процесс на камеру;
detect/embed/match масштабируются добавлением подов в свою Kafka
consumer-group (`docker compose up --scale detect=3`, или `detect.replicas`/HPA
в Helm-чарте). Ни один CPU-bound кусок кода не выполняется внутри asyncio
event loop.

### Frame sampling + tracking (спека, раздел 4)

`services/tracking/tracker.py` гоняет IoU/Kalman-трекер (norfair) на каждую
камеру. Детекция всё ещё выполняется на каждом кадре (дёшево); что реально
прореживается — это **эмбеддинг** (дорого): трек уходит на embed только на
первом кадре и затем каждые `embed_interval_frames` кадров. См.
[tests/unit/test_tracker.py](tests/unit/test_tracker.py).

### Распределённый трейсинг через Kafka-хоп

HTTP получает trace context бесплатно от OTel-инструментатора FastAPI, а
Kafka-сообщение — нет. `libs/black_ice_common/tracing.py` вручную
инжектирует/извлекает W3C `traceparent` через заголовки Kafka-сообщений, так
что весь путь одного кадра с камеры (ingest → detect → embed → match)
показывается в Jaeger как один трейс. Проверено в
[tests/unit/test_tracing.py](tests/unit/test_tracing.py).

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r services/match/requirements.txt   # или requirements.txt любого другого сервиса
python scripts/fetch_demo_frames.py               # берёт демо-кадр из тестовых данных самого InsightFace

cd infra
docker compose up --build              # основной пайплайн: redpanda, qdrant, postgres, ingest(demo), detect, embed, match, ui
docker compose --profile observability up -d   # + prometheus, grafana, jaeger
```

- Match API: `http://localhost:8000` (документация на `/docs`, метрики на `/metrics`)
- Netrunner UI (демо): `http://localhost:8080`
- Admin-консоль: `http://localhost:5174` (или `cd admin-ui && npm run dev` → `:5173`) — см. [admin-ui/README.md](admin-ui/README.md)
- Grafana: `http://localhost:3000` (анонимный admin) · Prometheus: `:9090` · Jaeger: `:16686`

Демо-режим (`SOURCE=demo` у ingest) зацикливает один вшитый тестовый снимок как
фейковый поток с камеры — весь пайплайн можно увидеть в работе без вебкамеры и
RTSP-источника. Для реального потока укажи в `SOURCE` `0` (вебкамера) или
`rtsp://`-адрес.

### API

| Эндпоинт | Роль | Примечания |
|---|---|---|
| `POST /enroll` | admin | `name`, `consent=true`, `file`; опционально `identity_id` — добавить ещё один сэмпл существующей личности (спека: multi-embedding per identity) |
| `POST /identify` | operator, admin | возвращает `IDENTITY CONFIRMED` / `IDENTITY UNKNOWN` (open-set — никогда "похоже на") |
| `GET /audit` | admin | последний лог решений о доступе |
| `DELETE /identities/{id}` | admin | отзыв согласия / право на удаление — удаляет запись личности и все её эмбеддинги |
| `GET /cameras`, `POST /cameras`, `PATCH /cameras/{id}`, `DELETE /cameras/{id}` | admin (`cameras`) | реестр камер — см. Milestone 2 ниже |
| `GET /cameras/{camera_id}/config`, `POST /cameras/{camera_id}/heartbeat` | **без RBAC** | вызываются самим ingest-процессом, не оператором — см. честную оговорку в Milestone 2 |
| `GET /access-rules`, `POST /access-rules`, `PATCH /access-rules/{id}`, `DELETE /access-rules/{id}` | admin (`access_rules`) | правила "кто/где/когда" — см. Milestone 3 ниже |
| `GET /alert-rules`, `POST /alert-rules`, `PATCH /alert-rules/{id}`, `DELETE /alert-rules/{id}` | admin (`alert_rules`) | webhook-уведомления на события — см. Milestone 4 ниже |
| `GET /health`, `GET /metrics` | — | |
| `WS /ws/live` | — | живой терминальный фид для UI, питается из Kafka-потока embed→match |

Авторизация — `X-API-Key` → роль, настраивается через `BLACK_ICE_API_KEYS=key:role,...`
(дефолтные dev-ключи: `dev-admin-key`, `dev-operator-key`). `AUTH_BACKEND=oidc`
переключает на реальный Keycloak вместо статичных ключей — см.
["Реальный IdP (Keycloak)"](#реальный-idp-keycloak) ниже.

```bash
curl -F "name=Neo" -F "consent=true" -F "file=@face.jpg" -H "X-API-Key: dev-admin-key" http://localhost:8000/enroll
curl -F "file=@face.jpg" -H "X-API-Key: dev-operator-key" http://localhost:8000/identify
```

## Тесты

```bash
pip install -r services/match/requirements.txt pytest
python scripts/fetch_demo_frames.py
python -m pytest tests/unit tests/integration -q
```

Для тестового набора не нужны Kafka/Postgres/Qdrant — юнит-тесты гоняют чистую
логику (decision, tracker, проброс trace-контекста, математику FAR/FRR),
интеграционные тесты запускают настоящие ONNX-модели против вшитого тестового
лица и match API против sqlite + in-memory Qdrant. Всё проверено на реальных
данных, а не на моках — включая регрессионный тест
([tests/integration/test_detect_embed_handoff.py](tests/integration/test_detect_embed_handoff.py))
на реальный баг, пойманный в процессе разработки: слишком узкий отступ у crop
между detect и embed незаметно портил качество эмбеддинга (косинусное сходство
0.97 вместо >0.999), обрезая выравнивающий warp ArcFace.

Нагрузочный тест: `locust -f tests/load/locustfile.py --host http://localhost:8000`.

## Admin-консоль (Фаза 1, Milestone 1)

`admin-ui/` — React/TS/Vite/Tailwind SPA, полноценная операционная консоль
вместо curl и одностраничного demo (`ui/index.html`, который остаётся
отдельно, никуда не делся). Подробности — [admin-ui/README.md](admin-ui/README.md).

Потребовало реальных изменений в бэкенде, не только фронт:
- **RBAC переведён с env var на БД**: новая таблица `ApiKey`
  ([libs/black_ice_common/db.py](libs/black_ice_common/db.py)) вместо парсинга
  `BLACK_ICE_API_KEYS` на каждый запрос. `BLACK_ICE_API_KEYS` не исчез — он
  теперь одноразовый bootstrap-сид при пустой таблице, так что старые
  compose/K8s-конфиги продолжают работать без изменений (проверено — все
  существующие тесты прошли без единой правки после миграции)
- Новые эндпоинты: `POST /auth/login`, `GET /identities`, фильтры/пагинация у
  `GET /audit` (`camera_id`/`identity_id`/`from_ts`/`to_ts`/`offset`)
- CORS-мидлварь (`CORS_ALLOWED_ORIGINS`) — раньше не был нужен, у API не было
  браузерного клиента

**Реальный баг, пойманный именно этой работой, не найденный ни разу за всю
предыдущую сессию**: `DELETE /identities/{id}` был сломан на настоящем
Postgres — падал с `ForeignKeyViolation`, если у личности была хоть одна
запись в `audit_log`. Все 42 прошлых теста были зелёными, потому что sqlite
по умолчанию не проверяет foreign key constraints вообще. Исправлено: (1)
`audit_log.identity_id` теперь `ON DELETE SET NULL` (сохраняет доку, ровно
как обещал докстринг), (2) в `db.py` добавлен listener, включающий
`PRAGMA foreign_keys=ON` для sqlite-соединений — то же самое немедленно
поймало ВТОРОЙ такой же баг в тесте `test_shadow_report.py` (фейковые
`identity_id`, не существующие в таблице `identities`). Оба зафиксированы
регрессионными тестами
([tests/integration/test_revoke_with_audit_history.py](tests/integration/test_revoke_with_audit_history.py)).

Проверено вживую (не sqlite): логин, dashboard с live-фидом через
`/ws/live`, enroll → identify → revoke через реальные Postgres+Qdrant
контейнеры, и RBAC-граница — роль без прав видит явное сообщение
"нет доступа", а не молча пустую таблицу (тоже реальный баг, найденный и
исправленный по ходу — TanStack Query по умолчанию ретраит 401/403 несколько
секунд, отсюда была "тишина" вместо ошибки).

## Camera/site management (Фаза 1, Milestone 2)

Реестр камер в admin-ui вместо ручного редактирования `docker-compose.yml`/Helm
values для каждой новой камеры.

Что изменилось в бэкенде:
- Новая модель `Camera` ([libs/black_ice_common/db.py](libs/black_ice_common/db.py))
  — `camera_id` (стабильный ключ, тот же что в env `CAMERA_ID` у ingest),
  `name`, `source`, `site`, `enabled`, `ingest_fps`, `last_seen_at`
- 6 эндпоинтов в [services/match/app/main.py](services/match/app/main.py) —
  CRUD за новым RBAC-правом `cameras` (только admin), плюс `config`/`heartbeat`
- `services/ingest/main.py` при старте (когда `SOURCE != demo`) больше не
  читает `SOURCE`/`INGEST_FPS` из env напрямую — тянет их через
  `GET /cameras/{camera_id}/config` (`_resolve_config`, с ретраями на
  временные сбои, жёстким отказом на 404/403), затем раз в 5с шлёт
  `POST /cameras/{camera_id}/heartbeat` в фоновом потоке. `SOURCE=demo`
  по-прежнему не требует match вообще — вся регистрозависимая логика
  пропускается

**Честная оговорка**: `GET /cameras/{id}/config` и `POST /cameras/{id}/heartbeat`
— единственные два эндпоинта во всём API без `require()`. У ingest-процессов
сегодня нет собственного API-ключа, а выпускать им ключ ради двух этих вызовов
— отдельное решение, сознательно отложенное, а не забытое. Пока считается
приемлемым, т.к. оба эндпоинта не раскрывают и не изменяют ничего чувствительнее
"какая у камеры конфигурация" / "камера жива" — но это реальная дыра в
периметре сети, если match когда-нибудь окажется доступен не только другим
сервисам в той же docker-сети/namespace.

Heartbeat — отдельный HTTP-вызов от ingest, не выведен из существующей
Prometheus-метрики `black_ice_frames_ingested_total{camera_id}`: match никуда
больше не ходит в Prometheus, и заводить эту зависимость только ради "жива ли
камера" — более тяжёлая связанность, чем HTTP-клиент, который у ingest и так
уже есть для конфига.

Проверено вживую (не только моки): реальный ingest-контейнер
(`docker compose run --rm --no-deps -e CAMERA_ID=... -e SOURCE=unused -e
MATCH_API_URL=http://match:8000 ingest`) реально получил `source`/`fps` от
только что зарегистрированной через `POST /cameras` камеры — подтверждено по
логам, не по факту "тест прошёл". В admin-ui: создание/редактирование
(toggle enabled → disabled, бейдж меняется)/удаление камеры через реальный UI
против реальных Postgres+match, включая RBAC-границу для роли operator.

### Динамическая оркестрация ingest-процесса

Изначально camera registry только конфигурировал камеру, но не поднимал под
неё ingest — назначение оставалось ручным деплой-шагом. Теперь это опционально
автоматизировано: [libs/black_ice_common/ingest_orchestrator.py](libs/black_ice_common/ingest_orchestrator.py),
переключается `ORCHESTRATOR_BACKEND`:

- `none` (по умолчанию) — старое поведение без изменений, ручной деплой
- `docker` — локальная разработка: match говорит с Docker Engine API
  (нужен смонтированный `/var/run/docker.sock`, см. `infra/docker-compose.yml`),
  сам поднимает/убирает контейнер `black-ice-ingest-{camera_id}`
- `kubernetes` — прод-цель: создаёт/удаляет Deployment той же формы, что
  статичные записи `ingest.cameras` в Helm values, только по API, а не при
  `helm install`. Требует RBAC у ServiceAccount match'а — рендерится только
  когда `orchestratorBackend: kubernetes`
  ([infra/k8s/black-ice/templates/ingest-orchestrator-rbac.yaml](infra/k8s/black-ice/templates/ingest-orchestrator-rbac.yaml)),
  ограничен `deployments` в своём namespace, не кластерный grant

`POST /cameras` разворачивает процесс сразу при регистрации; `DELETE` и
переключение `enabled` через `PATCH` — сворачивают/разворачивают его же. Ни
reconciliation-цикла, ни health-check поверх того, что уже даёт сам backend
(restart policy у Docker / Deployment controller у K8s) — осознанно, это
покрывает только два момента, которые реально важны: камеру зарегистрировали/
включили, или удалили/выключили.

Проверено вживую (`docker`-бэкенд): реальный `POST /cameras` создал реальный
Docker-контейнер на реальной сети compose, `DELETE` и `PATCH enabled=false/true`
корректно убирали/пересоздавали его, повторный вызов идемпотентен. Заодно
найден и починен смежный баг: `MATCH_API_URL` не был прокинут в Helm-чарте
вообще — ни у старых статичных `ingest.cameras`-подов, ни у новых
динамических (`configmap.yaml`).

## Access rules engine (Фаза 1, Milestone 3)

До этого момента `/identify` и живой Kafka-пайплайн решали доступ чисто по
биометрии: похож на порог — `IDENTITY CONFIRMED`, не похож —
`IDENTITY UNKNOWN`. Никакого понятия "где" и "когда" identity разрешён вход
не было — а именно это подразумевает "access control" в названии проекта.

**Модель**: новая таблица `AccessRule`
([libs/black_ice_common/db.py](libs/black_ice_common/db.py)) — `identity_id`
(обязателен), `camera_id` (NULL = все камеры), `weekdays` (CSV `mon..sun`,
NULL = каждый день), `start_time`/`end_time` (NULL = весь день), `enabled`.

**Default-deny, не default-allow**: у identity без единого совпавшего
включённого правила — отказ на любой камере. Это осознанный выбор
безопасного дефолта для физического контроля доступа: fail-open (доступ
разрешён, пока явно не запрещён) означал бы, что только что заведённое лицо
получает доступ везде, пока кто-то не вспомнит его ограничить — недопустимо
для системы, которая физически открывает двери.

**Где именно подключено**: только к живому Kafka-пайплайну
([services/match/app/stream_consumer.py](services/match/app/stream_consumer.py)),
не к `POST /identify`. Причина — `POST /identify` в принципе не принимает
`camera_id` в запросе (это ручной/тестовый путь, не физическая точка входа),
а вот каждый кадр из живого пайплайна несёт `camera_id`
([EmbeddingMsg](libs/black_ice_common/schemas.py)) — только там решение
"куда именно" физически осмысленно. `evaluate_embedding`
([libs/black_ice_common/decisioning.py](libs/black_ice_common/decisioning.py))
получил опциональный параметр `access_check` (по умолчанию `None`) —
stream_consumer передаёт туда `access_rules.is_access_allowed`, а
shadow-mode консьюмер сознательно не передаёт ничего: его задача — сравнивать
биометрическую точность модели-кандидата, а не решения о доступе, и
завязывать его на access-правила было бы лишней и неверной связанностью.
Статус в live-фиде теперь `ACCESS GRANTED`/`ACCESS DENIED` (при совпавшем
лице) вместо голого `IDENTITY CONFIRMED`; `AuditLog` получил колонку
`access_granted` (`NULL` — проверка не выполнялась, `true`/`false` — реальный
результат) — биометрическое совпадение и итоговое решение о доступе теперь
две разные, обе аудируемые вещи.

**API**: `/access-rules` CRUD за новым RBAC-правом `access_rules`
(только admin), плюс страница в admin-ui
([admin-ui/src/pages/AccessRules.tsx](admin-ui/src/pages/AccessRules.tsx)) —
таблица правил, выбор identity/камеры из уже существующих `/identities` и
`/cameras`, чекбоксы дней недели, `<input type="time">` для окна.

Проверено вживую (не только моки): реальный `POST /access-rules` создал
правило в реальном Postgres, `is_access_allowed` дал верный ответ по этим
самым данным через реальное соединение, CASCADE-удаление правил при удалении
identity подтверждено на реальном Postgres (новый `ondelete="CASCADE"`,
в отличие от `AuditLog`'а с его `SET NULL` — здесь удаление identity должно
удалить её правила, не осиротить их). В admin-ui: создание правила и с
дефолтным "каждый день, весь день", и с явными днями недели +
временным окном, и удаление — всё через реальный UI против реального Postgres.

Окна, пересекающие полночь (например, 22:00–06:00), поддержаны: день недели
правила — это день, когда смена *началась*, не календарная дата в момент
проверки (см. `access_rules.py`'s `_rule_matches_now`).

## Alerting config (Фаза 1, Milestone 4)

Webhook-уведомления на бизнес/security-события — отдельный слой от
`observability/prometheus/alerts.yml`, который алертит ops-команду на инфра-
здоровье (латентность, error rate, дрейф модели). Этот слой конфигурируется
оператором через admin-ui, а не зашит в PromQL-файл, и отвечает на другой
вопрос: не "жив ли сервис", а "кому написать, когда identity X получил отказ
на камере Y" или "камера Z замолчала".

**Модель**: `AlertRule` ([libs/black_ice_common/db.py](libs/black_ice_common/db.py))
— `event_type` (`access_denied` | `camera_offline`), опциональные
`identity_id`/`camera_id`-фильтры (NULL = любой), `webhook_url`, `enabled`.

**Доставка**: [libs/black_ice_common/alerting.py](libs/black_ice_common/alerting.py)'s
`fire_alert()` — находит совпавшие включённые правила и шлёт каждому свой
POST-запрос в отдельном фоновом потоке, не блокируя вызывающий код (hot path
матчинга не должен ждать медленный/недоступный webhook-приёмник); неудачная
доставка логируется, не бросает исключение наружу.

**Точки срабатывания**:
- `access_denied` — прямо в `services/match/app/stream_consumer.py` в момент
  отказа, тот же живой Kafka-пайплайн, что и Milestone 3.
- `camera_offline` — ничто в проекте раньше не опрашивало staleness камеры
  (`last_seen_at` пишет только heartbeat самого ingest, см. Milestone 2), так
  что понадобился новый скрипт
  [scripts/camera_offline_check.py](scripts/camera_offline_check.py),
  запускаемый как K8s CronJob каждые 5 минут
  (`infra/k8s/black-ice/templates/camera-offline-cronjob.yaml`) — тот же
  паттерн, что уже используют `retention-cronjob.yaml`/`drift-monitor-cronjob.yaml`.

**Реальный баг, пойманный именно живой проверкой, не юнит-тестами**: скрипт-
версия — короткоживущий процесс, который запускается и сразу завершается.
`fire_alert()` изначально не возвращал ничего, и его background-поток
(`daemon=True`) убивался операционной системой мгновенно при выходе процесса
— то есть в реальном K8s CronJob'е алерты о выключенных камерах реально бы
никогда не отправлялись, хотя все юнит/интеграционные тесты (которые живут
внутри одного долгоживущего процесса pytest) этого не показывали. Пойман
только когда я гонял скрипт как настоящий одноразовый Python-процесс против
настоящего Postgres и настоящего локального HTTP-приёмника вебхуков — лог
приёмника оставался пустым. Исправлено: `fire_alert()` теперь возвращает
список запущенных потоков, и `camera_offline_check.py` явно их `join()`-ит
перед выходом. `stream_consumer.py` эту проблему никогда не имел бы — это
постоянно работающий процесс, поток успевает завершиться сам.

**Второй реальный баг, найденный тем же live-проходом** (не про алертинг
напрямую, а про admin-ui в целом): переключение роли в интерфейсе — логин
как admin, логаут, логин как operator, без перезагрузки страницы — показывало
закэшированные TanStack Query строки от предыдущей admin-сессии ПОД
сообщением "нет доступа" на странице Alert rules. Тот же баг обнаружился и
на Cameras/Access rules/Identities/Audit — везде, где `.map()` рендерит
`data` без проверки `!isError`, а `QueryClient` — модуль-синглтон, живущий
между логинами в одной вкладке. Для консоли контроля доступа это реальная
проблема: оператор, забравший ранее залогиненную вкладку админа, увидел бы
её кэшированные данные. Исправлено в одном месте, а не патчем в каждой
странице —
[admin-ui/src/contexts/AuthContext.tsx](admin-ui/src/contexts/AuthContext.tsx)
теперь вызывает `queryClient.clear()` и на `login()`, и на `logout()`.

**API**: `/alert-rules` CRUD за новым RBAC-правом `alert_rules` (только
admin), плюс страница в admin-ui
([admin-ui/src/pages/AlertRules.tsx](admin-ui/src/pages/AlertRules.tsx)).

Проверено вживую (не только моки): поднял реальный локальный HTTP-приёмник
вебхуков, реальный match против реального Postgres+Qdrant, зарегистрировал
identity/камеру/оба типа alert-правил через реальный API, и получил оба
реальных webhook-события (`access_denied` от прогона через
`stream_consumer._handle`, `camera_offline` от реального запуска
`camera_offline_check.py`) в логе приёмника. RBAC- и кэш-баг проверены через
реальные логин/логаут переходы в браузере, не только через unit-тесты.

Известное упрощение: без cooldown/rate-limiting на правило — часто
мигающая камера или identity могла бы запустить много потоков доставки
подряд; добавить, если это станет реальной проблемой (ponytail-комментарий
в коде указывает на это же место).

## Секреты в Vault

`DATABASE_URL` и `BLACK_ICE_API_KEYS` больше не обязаны жить в plaintext
env vars или в Helm `values.yaml` — раньше единственным способом их задать
был именно plaintext (`values.yaml`'s `connections.databaseUrl`/`apiKeys` →
обычный K8s `Secret`, который просто base64, не шифрование).

**Как это работает**: [libs/black_ice_common/secrets.py](libs/black_ice_common/secrets.py)'s
`get_secret(name, default)` — если `VAULT_ADDR`/`VAULT_TOKEN` не заданы (дефолт
для `docker compose up`/локальной разработки), просто читает обычный env var
или дефолт, Vault для этого пути не нужен вообще. Если заданы — читает секрет
по имени `name` из Vault KV v2 обычным `requests.get` (без клиента `hvac` —
проект и так уже зависит от `requests`, а чтение KV v2 это один GET, целая
клиентская библиотека ради этого избыточна). `config.py` переопределяет
`settings.database_url` через резолвер сразу после конструирования
`Settings()`; `rbac.py`'s `seed_from_env()` делает то же для
`BLACK_ICE_API_KEYS`.

```bash
# локально: реальный Vault dev-server (не для прода — фиксированный root-токен,
# in-memory, без TLS)
docker compose -f infra/docker-compose.yml --profile secrets up -d vault
vault kv put -address=http://localhost:8200 secret/black-ice \
  DATABASE_URL="postgresql+psycopg2://black_ice:black_ice@localhost:5432/black_ice" \
  BLACK_ICE_API_KEYS="my-admin-key:admin,my-operator-key:operator"
VAULT_ADDR=http://localhost:8200 VAULT_TOKEN=dev-vault-root-token \
  uvicorn services.match.app.main:app  # без DATABASE_URL/BLACK_ICE_API_KEYS в окружении
```

**Helm**: `values.yaml`'s `vault.enabled` (по умолчанию `false`). Когда
`true` — `templates/secret.yaml` вообще не рендерит plaintext `Secret`, а
`match`-деплоймент и все 3 CronJob'а (`retention`/`drift-monitor`/
`camera-offline-check`) вместо него получают `VAULT_TOKEN` из **внешнего**
`Secret`, названного `vault.vaultTokenSecretRef` — чарт сознательно не
создаёт и не хранит этот токен сам (это была бы та же plaintext-проблема,
просто переехавшая в другое поле), он ожидается от вашей интеграции с Vault
(Vault Agent Injector, External Secrets Operator, и т.п.). `VAULT_ADDR`/
`VAULT_KV_PATH` при этом уходят в обычный `ConfigMap`, т.к. это не секреты.

Проверено вживую (не только "выглядит правильно"): поднят настоящий
`hashicorp/vault` dev-сервер, туда реально записаны `DATABASE_URL`/
`BLACK_ICE_API_KEYS`, match запущен без единого plaintext-секрета в
окружении — подключился к правильной БД, засеял выданный Vault'ом API-ключ
в таблицу `api_keys`, и **отверг** старый статичный `dev-admin-key` (401),
подтверждая, что старые ключи не работают в обход Vault втихую. Helm-путь
проверен реально установленным `helm` (`helm lint` + `helm template --set
vault.enabled=true`), не вручную прочитанным YAML: подтверждено, что при
`vault.enabled=true` объект `Secret` не рендерится вообще, а все 4
workload'а (`match` + 3 CronJob'а) получают `envFrom` из
`vaultTokenSecretRef`.

Известное упрощение: `docker-compose`'s vault-сервис — dev-режим с
фиксированным root-токеном, не настоящий Vault-кластер; для прод-K8s
нужна отдельная настройка Vault auth-метода (K8s auth) — не входит в этот
чарт, только точка расширения (`vaultTokenSecretRef`).

## Реальный IdP (Keycloak)

Из списка "что нужно для реального продукта" в STATUS.md: статичные API-ключи
заменены реальной проверкой JWT против настоящего OpenID Connect провайдера
(Keycloak). Опционально — `AUTH_BACKEND=api_key` (по умолчанию) сохраняет
старое поведение без единого изменения; `AUTH_BACKEND=oidc` переключает
`require()`/`/auth/login` на проверку `Authorization: Bearer <token>` вместо
`X-API-Key`.

**Как это работает**: [libs/black_ice_common/oidc.py](libs/black_ice_common/oidc.py)
проверяет подпись/issuer/expiry токена через `PyJWT`+JWKS, достаёт роль из
`realm_access.roles` — реалм-роль в Keycloak должна называться буквально
`admin`/`operator`/`viewer`, отдельной таблицы маппинга нет, `rbac.ROLES`
остаётся единственным источником правды о том, что каждая роль может
делать, IdP это или API-ключ.
[libs/black_ice_common/rbac.py](libs/black_ice_common/rbac.py)'s
`_authenticate()` — общая точка входа для обоих способов, `require()` и
`/auth/login` больше не дублируют эту логику.

```bash
# локально: реальный Keycloak dev-server с уже готовым realm'ом
# (admin/operator/viewer роли + 3 dev-пользователя) — infra/keycloak/realm-export.json
docker compose -f infra/docker-compose.yml --profile idp up -d keycloak
# .env для match:
#   AUTH_BACKEND=oidc
#   OIDC_ISSUER_URL=http://localhost:8180/realms/black-ice
#   OIDC_DISCOVERY_URL=http://keycloak:8080/realms/black-ice
```

Два разных URL не опечатка: браузер достаёт Keycloak только через
опубликованный порт (`localhost:8180`), а match — через compose-имя сервиса
(`keycloak:8080`). `KC_HOSTNAME` в Keycloak зафиксирован на `localhost:8180`,
поэтому **любой** токен несёт именно этот `iss`, независимо от того, каким
путём его выдали — так что `OIDC_ISSUER_URL` (что проверяется) и
`OIDC_DISCOVERY_URL` (откуда match реально качает JWKS) могут различаться
без риска принять подделанный issuer. В проде это обычно один и тот же
публичный хостнейм, `OIDC_DISCOVERY_URL` не нужен вообще.

**admin-ui**: `VITE_AUTH_MODE=oidc` (плюс `VITE_OIDC_URL`/`VITE_OIDC_REALM`/
`VITE_OIDC_CLIENT_ID`) переключает страницу логина с формы API-ключа на
кнопку "Sign in with Keycloak" —
[keycloak-js](admin-ui/src/lib/keycloak.ts), настоящий Authorization Code +
PKCE, не самодельный поток. `public/silent-check-sso.html` восстанавливает
сессию через скрытый iframe при перезагрузке страницы без видимого редиректа.

**Helm**: `values.yaml`'s `auth.backend` (по умолчанию `"api_key"`) — при
`"oidc"` `ConfigMap` получает `OIDC_ISSUER_URL`/`OIDC_DISCOVERY_URL`, `apiKeys`
при этом продолжает рендериться (переключение назад не требует передеплоя
секретов).

Проверено вживую целиком, не по кускам: реальный Keycloak (realm-import из
`realm-export.json`), реальные парольные гранты для трёх dev-пользователей,
реальные JWT с настоящей RSA-подписью — проверены реальным `match` (роль
admin получила 200 на `/identities`, operator/viewer — честные 403, мусорный
токен и `X-API-Key` в oidc-режиме — 401, без тихого fallback'а). Плюс
браузер, не только curl: настоящий редирект-логин в Keycloak через admin-ui
(dev-admin/dev-admin), возврат с ролью Admin, сессия пережила `F5` (silent
SSO), logout корректно разлогинил через Keycloak. `helm lint`+`helm template`
в обоих режимах.

Известное упрощение: одна Keycloak-роль на пользователя ожидается в токене
(берётся первая распознанная) — множественные пересекающиеся роли не
разруливаются отдельной логикой приоритета, этого не требовалось ни одним
существующим сценарием.

## HA/DR

Из списка "что нужно для реального продукта" в STATUS.md: бэкап/восстановление
для Postgres и Qdrant, плюс честная граница — этот чарт **не** даёт
кластерную HA (репликацию/автофейловер) сама по себе, см. ниже почему.

**Что именно бэкапится и почему обоих хранилищ**: Postgres держит
identities/audit_log/api_keys/cameras/access_rules/alert_rules — весь
реляционный стейт системы контроля доступа; Qdrant держит сами лицевые
эмбеддинги. Потеря любого одного без другого — это либо рабочая система без
истории/правил, либо история без единой возможности кого-либо узнать
(эмбеддинги специально не хранятся в Postgres, только в Qdrant — см.
Архитектуру). Бэкап должен покрывать оба хранилища синхронно.

- **Postgres** — [scripts/backup_postgres.py](scripts/backup_postgres.py) /
  [restore_postgres.py](scripts/restore_postgres.py), обёртки над
  `pg_dump -Fc`/`pg_restore --clean --if-exists` (custom-формат — сжатый,
  поддерживает выборочное/параллельное восстановление, это тот формат, что
  реально используют в проде, не голый SQL-дамп). Нужен `postgresql-client`
  в образе — добавлен в [services/match/Dockerfile](services/match/Dockerfile).
- **Qdrant** — [scripts/backup_qdrant.py](scripts/backup_qdrant.py) /
  [restore_qdrant.py](scripts/restore_qdrant.py): создаёт снапшот через
  Qdrant's snapshot API у конкретной коллекции за алиасом (`collection_name`
  — алиас, не сырое имя коллекции, см. `vectorstore.alias_target`), скачивает
  файл снапшота на диск обычным `requests.get` (оставлять его только внутри
  папки снапшотов Qdrant — не бэкап: она на том же volume, что и сама
  коллекция, теряются вместе), при восстановлении — заливает файл обратно
  через Qdrant's upload-эндпоинт в свежую коллекцию и атомарно переключает
  алиас на неё (тот же swap-паттерн, что и `reindex_faces.py`).
- **K8s**: `templates/backup-cronjob.yaml` — ежедневно (настраивается,
  `values.yaml`'s `backupCronJob`), гоняет оба скрипта в один под, пишет на
  `PersistentVolumeClaim` (`backup-pvc.yaml`) — бэкапы обязаны пережить под,
  который их сделал, иначе это не бэкап, а копия на той же временной
  файловой системе.

**Проверено вживую по-настоящему, не "выглядит правильно"**: реальный
Postgres/Qdrant с реальными вживую внесёнными данными (identities Neo/Smith/
Morpheus/Trinity из тестирования Milestone 3/4) — снят реальный Qdrant-снапшот
(67MB tar), **коллекция целиком удалена** (`DELETE /collections/faces_v1` —
настоящая имитация потери данных, не мок), восстановлена из скачанного файла
через `restore_qdrant.py`, и через сам алиас `faces` (как это делает
production-код) подтверждены те же самые 4 точки с теми же payload'ами
(`identity_id`/`name`) что были до удаления.

**Честная граница — то, чего это НЕ даёт**: это point-in-time бэкап/восстановление
вручную/по расписанию, не кластерная HA с автоматическим failover.
Как и Kafka/Qdrant/Postgres сами по себе (см. "Стейтфул-зависимости... не
вшиты в этот чарт" выше) — настоящая репликация Postgres (стриминг + автоматический
failover) должна ставиться через отдельный оператор (например, CloudNativePG
или Zalando's postgres-operator), а не пересобираться внутри этого чарта; то
же для кластеризации самого Qdrant. RTO/RPO этого CronJob'а — до 24 часов
данных (при дефолтном ежедневном расписании) и время ручного/скриптового
восстановления, не "секунды на автоматический failover".

## Kubernetes / Helm

```bash
helm lint infra/k8s/black-ice
helm template black-ice infra/k8s/black-ice | less
helm install black-ice infra/k8s/black-ice -f my-values.yaml
```

Стейтфул-зависимости (Kafka, Qdrant, Postgres) **не** вшиты в этот чарт —
ставь их через собственные официальные чарты и просто укажи строки
подключения в `values.yaml` (`connections.*`). Пихать стейтфул-инфру в чарт
приложения — это как раз та связанность, из-за которой потом больно апгрейдить
и бэкапить. Проверено оффлайн (в деве нет кластера) через `helm lint` +
`helm template` + `kubeconform -strict` против настоящих OpenAPI-схем
Kubernetes, на дефолтных значениях, с включённым GPU для embed, с несколькими
камерами и с выключенным HPA.

У `detect`/`embed`/`match` у каждого свой HPA по CPU. `ingest` — один
Deployment на камеру (список `ingest.cameras` в `values.yaml`) — никогда не
масштабируется числом реплик, по той же причине про GIL выше. `CronJob`
ежедневно гоняет чистку по retention
([scripts/purge_expired.py](scripts/purge_expired.py)).

## Observability

Prometheus скрейпит `/metrics` каждого сервиса (свои counter/histogram в
[libs/black_ice_common/metrics.py](libs/black_ice_common/metrics.py));
автопровижининг дашборда в Grafana (кадры/детекции/эмбеддинги в секунду,
решения о доступе, p99-латентность по стадиям); Jaeger — для описанных выше
распределённых трейсов; [observability/prometheus/alerts.yml](observability/prometheus/alerts.yml)
алертит на p99-латентность, error rate матчинга (сработал circuit breaker),
мёртвый фид с камеры и дрифт (ниже). Правила проверены `promtool check
rules/config`.

### Мониторинг дрифта

В проде нет ground truth, чтобы сверять точность, поэтому
[scripts/drift_report.py](scripts/drift_report.py) следит за прокси-метрикой:
двухвыборочный тест Колмогорова-Смирнова между базовым и недавним окном
скоров подтверждённых матчей из audit-лога. Значимый сдвиг значит, что
*что-то* поменялось (модель, состав людей, камера/освещение, устаревшая
галерея) — тест сигнализирует, а не диагностирует причину. Пушит в
Prometheus Pushgateway (`docker compose --profile observability up`, либо
`driftMonitorCronJob` в Helm-чарте, по умолчанию раз в час), потому что
CronJob не живёт достаточно долго, чтобы его скрейпить напрямую. Сама
статистика протестирована на синтетических распределениях
([tests/unit/test_drift_report.py](tests/unit/test_drift_report.py)); логика
запроса окон — на реальном (sqlite) audit-логе
([tests/integration/test_drift_report_db.py](tests/integration/test_drift_report_db.py)).

### Re-index/re-shard без даунтайма

`collection_name` в Qdrant — это **алиас**, а не сама коллекция: все вызовы
upsert/search всегда идут через алиас, а резолвит его сам Qdrant на своей
стороне. [scripts/reindex_faces.py](scripts/reindex_faces.py) создаёт новую
конкретную коллекцию с другими параметрами HNSW (`--m`/`--ef-construct`) или
числом шардов (`--shards`), копирует туда все точки, а затем атомарно
переключает алиас — читатели и писатели никогда не видят момент, когда алиас
указывает в никуда. Проверено полностью end-to-end на local-режиме Qdrant:
резолв алиаса, миграция точек, запись после переключения
([tests/integration/test_reindex.py](tests/integration/test_reindex.py)).
Честная оговорка: local/embedded-режим Qdrant молча игнорирует кастомные
параметры HNSW (всегда отдаёт дефолты) и всегда делает brute-force поиск
независимо от `search_params` — проверена именно *механика переключения
алиаса*, а реальный эффект `hnsw_m`/`hnsw_ef_construct`/`hnsw_ef_search` на
recall/латентность нужно смотреть на настоящем сервере Qdrant.

### Shadow-mode деплой модели

Оценивает модель-кандидата на живом трафике до того, как её продвигать —
никогда не влияет на реальное решение о доступе. У другой модели другое
пространство эмбеддингов, так что это не простое сравнение бок о бок:
`SHADOW_EMBEDDING_ENABLED=true` заставляет `/enroll` писать *одновременно* в
основную галерею и в отдельную галерею `faces_shadow` (моделью-кандидатом, по
умолчанию `buffalo_s` — меньший и быстрее пак InsightFace, реалистичный сценарий
"а не перейти ли нам на модель подешевле"), а embed-воркер публикует
параллельный эмбеддинг в `faces.embedded.shadow`. Отдельный consumer
([services/match/app/shadow_consumer.py](services/match/app/shadow_consumer.py))
ищет по shadow-галерее и пишет в ту же таблицу `audit_log` с меткой
`model_version=<pack>`, коррелируя по `(frame_id, track_id)` — свой
CircuitBreaker гарантирует, что сломанная модель-кандидат никогда не
задеградирует основной путь. [scripts/shadow_report.py](scripts/shadow_report.py)
джойнит решения primary и shadow по этому ключу и считает процент совпадений
до того, как продвигать кандидата. Весь пайплайн проверен — запись в обе
галереи, корректное логирование shadow-решения без касания основного
audit-трейла
([tests/integration/test_shadow_mode.py](tests/integration/test_shadow_mode.py)),
и математика agreement rate на синтетических случаях совпадения/расхождения
([tests/integration/test_shadow_report.py](tests/integration/test_shadow_report.py)).

## Security и compliance

- **RBAC**: статическая мапа API-key → роль ([libs/black_ice_common/rbac.py](libs/black_ice_common/rbac.py)).
  ponytail: нет настоящего IdP — поменять на OIDC/JWT, когда появится реальный identity provider.
- **Rate limiting**: slowapi, по каждому роуту, по умолчанию 30/мин.
- **Circuit breaker**: pybreaker вокруг вызовов Qdrant/Postgres в
  stream-consumer — быстрый отказ вместо накопления латентности, когда
  зависимость лежит.
- **Consent + retention**: `/enroll` требует `consent=true`; у каждой личности
  есть `retention_expires_at`; CronJob чистит и строку в Postgres, и все
  векторы в Qdrant для истёкших личностей.
- **Audit log**: каждое решение о доступе (matched/unmatched, score, роль
  запросившего, камера) — намеренно ключуется по `identity_id`, а не по
  биометрии, чтобы лог оставался полезным даже после удаления личности.
- **Open-set recognition**: ниже `MATCH_THRESHOLD` ответ всегда `UNKNOWN`,
  никогда "похоже на".
- **Liveness**: [libs/black_ice_common/liveness.py](libs/black_ice_common/liveness.py)
  состоит из двух слоёв. (1) Классическая мульти-сигнальная эвристика —
  резкость по Лапласу + дисперсия хромы в YCrCb ("color-texture analysis",
  тот же класс сигналов, что использует настоящая антиспуфинг-литература), но
  это всё равно именно эвристика: ловит плоское фото-распечатку или экранный
  replay, не больше. (2) `LivenessOnnxEngine` — настоящая точка подключения
  *обученного* классификатора через уже имеющуюся в проекте зависимость
  onnxruntime — укажи `LIVENESS_ONNX_MODEL_PATH` на сконвертированный
  чекпоинт (например, MiniFASNet/Silent-Face-Anti-Spoofing, экспортированный
  в ONNX), чтобы использовать его вместо эвристики. Такая модель здесь не
  поставляется: очевидный готовый вариант (встроенный антиспуфинг в
  `deepface`) тянет за собой TensorFlow+Keras+pandas как новые жёсткие
  зависимости и ломает пин `numpy<2`/onnxruntime-only стек этого проекта — это
  подтверждено реальной попыткой установить его в ходе разработки, а не
  предположение. Проводка плагина (препроцессинг, инференс, разбор вывода)
  проверена на вручную собранной игрушечной ONNX-модели
  ([tests/unit/test_liveness.py](tests/unit/test_liveness.py)), независимо от
  какого-либо конкретного обученного чекпоинта. Выключено по умолчанию
  (`LIVENESS_CHECK_ENABLED=false`) — у эвристического пути есть реальный
  процент ложных отказов на дешёвых вебкамерах.
- **Осведомлённость про model inversion**: по проводам и в логи уходят только
  512-мерные эмбеддинги и короткоживущие JPEG-кропы — сырые фото при
  регистрации нигде не сохраняются. Сами эмбеддинги в принципе всё ещё
  обратимы (атаки model inversion на эмбеддинги лиц — активная область
  исследований); template protection (например, cancelable biometrics,
  гомоморфно-зашифрованные шаблоны) здесь не реализован — отмечен как
  следующий шаг усиления, не решённая задача.

## Калибровка (FAR/FRR, ROC/DET)

```bash
pip install -r ml/eval/requirements.txt
python ml/eval/roc_calibration.py --dataset /путь/к/lfw-style/датасету --out roc.png
```

Считает распределения косинусного сходства genuine/impostor, печатает порог
equal-error-rate, строит кривые ROC + DET. Сама математика FAR/FRR/EER
покрыта юнит-тестами на синтетических хорошо разделённых и перекрывающихся
распределениях
([tests/unit/test_roc_calibration.py](tests/unit/test_roc_calibration.py))
независимо от какого-либо реального датасета.

## Что упрощено (и путь апгрейда)

- **Alembic**: схема управляется через `create_all()`; добавить настоящие
  миграции, когда схеме придётся эволюционировать на живых данных.
- **GPU/TensorRT**: всё работает на `CPUExecutionProvider`; поменять провайдер
  ONNX Runtime (и флаг `embed.gpu.enabled` в Helm, уже проведённый) когда
  появится GPU node pool.
- **Схемы сообщений**: обычный JSON, не Avro + schema registry — добавить,
  если появится второй язык потребителя или реальная эволюция схемы.
- **Tracking — библиотека, а не сервис**: `services/tracking/tracker.py`
  выполняется в процессе внутри `detect`, а не как отдельный сервис через
  Kafka — ему нужно плотное покадровое состояние на камеру, и сетевой хоп
  тут только замедлил бы дело.
- **HNSW/re-index** — механика alias-swap и сами параметры (`m`/`ef_construct`)
  проверены на настоящем Qdrant-сервере (см. [PHASE0_RESULTS.md](PHASE0_RESULTS.md));
  не проверен реальный эффект на recall/латентность под нагрузкой — это уже
  отдельный вопрос тюнинга, не механики.
- **Liveness / template protection**: у liveness теперь есть настоящая точка
  подключения обученной модели, но сама обученная модель не поставляется (см.
  раздел Security); model-inversion/template-protection — по-прежнему только
  осведомлённость, не реализация.
- **Ingest-facing эндпоинты без API-ключа**: `GET /cameras/{id}/config` и
  `POST /cameras/{id}/heartbeat` не защищены `require()`, т.к. у
  ingest-процессов сегодня нет собственного ключа — апгрейд: выпускать
  каждому ingest свой API-ключ с отдельной ролью `ingest`, ограниченной
  только этими двумя маршрутами.
- **Access rules не применяются к `POST /identify`**: это осознанная граница
  (ручной/тестовый эндпоинт без `camera_id` в запросе, не физическая точка
  входа), не забытое место — см. Milestone 3 выше.
- **Alert rules без cooldown/rate-limiting**: часто срабатывающее правило
  (мигающая камера, повторяющиеся отказы одной identity) шлёт webhook на
  каждое совпадение — апгрейд: last-fired timestamp на `AlertRule` и
  минимальный интервал между доставками одного правила.

## Структура репозитория

```
black-ice/
├── services/{ingest,detect,embed,match,tracking}/  — код каждого этапа + Dockerfile
├── libs/black_ice_common/                          — общий код: config/schemas/kafka/ml/rbac/tracing
├── infra/{docker-compose.yml,k8s/black-ice/}        — compose-стек + Helm-чарт
├── observability/{prometheus,grafana}/              — конфиг скрейпа, алерты, дашборды
├── ml/eval/                                         — калибровка ROC/FAR-FRR
├── ui/index.html                                    — netrunner-стилизованный демо: терминал + ручной скан
├── admin-ui/                                         — React-консоль для операторов (Фаза 1) — см. admin-ui/README.md
├── scripts/                                         — фетч демо-кадров, чистка по retention, reindex, отчёты drift/shadow
├── tests/{unit,integration,load}/
└── .github/workflows/ci.yml                         — lint, тесты, сборка каждого образа, helm lint+validate
```
