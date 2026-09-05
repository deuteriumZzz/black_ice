# BLACK ICE — статус по этапам

Сверка с роадмапом и чеклистом senior+ фич из `BLACK_ICE_spec.md`. ✅ сделано и
протестировано · ⚠️ сделано частично / с честной оговоркой · ❌ не делали.

## Роадмап (раздел 6 спеки)

| Этап | План | Статус |
|---|---|---|
| Нед 1-2 | Монолит: detect→embed→search→API | ✅ (эволюционировал в сервисы ниже) |
| Нед 3-4 | Разбить на сервисы, Kafka между стадиями | ✅ [services/](services), Redpanda |
| Нед 5-6 | Docker → Kubernetes, Helm | ✅ [infra/k8s/black-ice](infra/k8s/black-ice) |
| Нед 7-8 | Observability: Prometheus/Grafana/tracing | ✅ [observability/](observability) |
| Нед 9+ | Security, антиспуфинг, calibration, нагрузка | ✅/⚠️ см. ниже |
| Фаза 0 (пост-спека) | Прогнать всё вживую, не на моках | ⚠️ см. [PHASE0_RESULTS.md](PHASE0_RESULTS.md) |
| Фаза 1, Milestone 1 (пост-спека) | Admin-консоль вместо curl | ✅ [admin-ui/](admin-ui) |
| Фаза 1, Milestone 2 (пост-спека) | Camera/site management | ✅/⚠️ см. ниже |
| Фаза 1, Milestone 3 (пост-спека) | Access rules engine | ✅ см. ниже |
| Фаза 1, Milestone 4 (пост-спека) | Alerting config | ✅ см. ниже |

## Качество распознавания

- ✅ Калибровка FAR/FRR, ROC/DET-кривая — [ml/eval/roc_calibration.py](ml/eval/roc_calibration.py).
  Прогнано на реальном LFW (1149 фото, 96 личностей): EER-порог 0.116, см.
  [PHASE0_RESULTS.md](PHASE0_RESULTS.md) — production-дефолт 0.45 остаётся
  оправданным (сознательный сдвиг в сторону меньшего FAR), теперь подтверждено данными
- ✅ Open-set recognition — ниже порога всегда `UNKNOWN`, не "похоже на"
- ✅ Multi-embedding per identity — `/enroll` с `identity_id` добавляет ещё один сэмпл

## Масштабируемость

- ✅ ANN-индекс (Qdrant HNSW), настраиваемые `hnsw_m`/`ef_construct`/`ef_search`.
  Проверено на реальном Qdrant-сервере (не local-режим) — custom `m=32`/`ef_construct=200`
  реально применились в `hnsw_config` коллекции, см. [PHASE0_RESULTS.md](PHASE0_RESULTS.md)
- ✅ Шардирование + re-index без даунтайма — [scripts/reindex_faces.py](scripts/reindex_faces.py), alias-swap
- ✅ Frame sampling + tracking — [services/tracking/tracker.py](services/tracking/tracker.py) (norfair)
- ✅ Async pipeline с очередями (Kafka consumer groups)

## Security

- ⚠️ Liveness — классическая эвристика (резкость+цвет) + честный ONNX plug-in point,
  без реальной обученной модели (deepface пробовали, сломала стек numpy/onnxruntime)
- ⚠️ Model inversion — только awareness в README, template protection не реализован
- ✅ Rate limiting (slowapi), circuit breaker (pybreaker)

## MLOps

- ✅ Drift monitoring — [scripts/drift_report.py](scripts/drift_report.py), KS-тест, Pushgateway
- ✅ Shadow-mode деплой — [services/match/app/shadow_consumer.py](services/match/app/shadow_consumer.py),
  вторая модель (buffalo_s) в отдельной галерее, [scripts/shadow_report.py](scripts/shadow_report.py)
- ✅ p99 latency + алерты — Grafana dashboard, [observability/prometheus/alerts.yml](observability/prometheus/alerts.yml)

## Compliance (встроено в архитектуру)

- ✅ Audit log — кто/когда/что, ключ по `identity_id`, не по биометрии
- ✅ Consent management — обязателен при `/enroll`, отзываемый через `DELETE /identities/{id}`
- ✅ Data retention — авто-удаление по `retention_expires_at`, CronJob
- ✅ Role-based access — API-key → роль (admin/operator/viewer), теперь через
  БД-таблицу `ApiKey` (было — парсинг env var на каждый запрос)

## UI

- ✅ [ui/index.html](ui/index.html) — demo: терминальный стиль, live-фид через WebSocket, ручной enroll/identify
- ✅ [admin-ui/](admin-ui) — настоящая консоль оператора (React/TS/Vite):
  логин, dashboard, identities (list/revoke), audit (фильтры/пагинация).
  Проверено вживую против реальных Postgres+Qdrant, включая RBAC-границу
  (403 показывается явно, не молчаливой пустой таблицей)
- ✅ Cameras (Milestone 2) — CRUD-реестр камер в admin-ui: `Camera` в БД
  (`libs/black_ice_common/db.py`), 6 эндпоинтов в `services/match/app/main.py`,
  ingest при старте тянет свой `source`/`ingest_fps` из реестра по `CAMERA_ID`
  вместо чтения из env напрямую (`services/ingest/main.py:_resolve_config`),
  плюс heartbeat каждые 5с. Проверено вживую: реальный ingest-контейнер против
  реального match+Postgres, не только моки. Динамическая оркестрация процесса
  под камеру — теперь тоже сделана: [libs/black_ice_common/ingest_orchestrator.py](libs/black_ice_common/ingest_orchestrator.py),
  переключается `ORCHESTRATOR_BACKEND` (`none` по умолчанию — сохраняет старое
  ручное поведение; `docker` для локальной разработки через Docker Engine API;
  `kubernetes` для прод-цели, создаёт/удаляет Deployment той же формы, что
  статичные записи `ingest.cameras` в Helm values, только по API, а не при
  `helm install`). `POST /cameras` разворачивает процесс, `DELETE` и
  переключение `enabled` через `PATCH` — сворачивают/разворачивают его же.
  Проверено вживую (`docker`-бэкенд): реальный `POST /cameras` создал реальный
  Docker-контейнер на реальной сети compose, `DELETE` и `PATCH enabled=false/true`
  удаляли/пересоздавали его корректно, повторный деплой идемпотентен (не плодит
  дубликат). `kubernetes`-бэкенд проверен как остальной Helm-код в этом
  репо — `helm lint`+`helm template` (RBAC рендерится только при
  `orchestratorBackend: kubernetes`, ServiceAccount/Role/RoleBinding
  ограничены `deployments` в своём namespace, не кластерный grant), плюс
  юнит-тесты на мок K8s-клиенте — реального кластера тут нет. Заодно
  найден и починен смежный баг: `MATCH_API_URL` вообще не был прокинут в
  Helm-чарте — ни у старых статичных `ingest.cameras`-подов, ни у новых
  динамических (оба брали default `localhost:8000`, недостижимый из пода).
- ⚠️ **Известный пробел**: `GET /cameras/{id}/config` и
  `POST /cameras/{id}/heartbeat` — единственные два эндпоинта без RBAC
  (`require()`), т.к. ingest-процессы сегодня не имеют своего API-ключа.
  Осознанно отложено, а не забыто — обе стороны компромисса описаны в
  докстрингах эндпоинтов ([services/match/app/main.py](services/match/app/main.py)).
- ✅ Access rules (Milestone 3) — реальные правила доступа "кто/где/когда"
  вместо голого биометрического порога. Новая модель `AccessRule`
  ([libs/black_ice_common/db.py](libs/black_ice_common/db.py)): identity_id +
  опциональные camera_id/дни недели/временное окно. **Default-deny**:
  identity без единого совпавшего правила получает отказ везде — сознательно
  выбранный fail-closed default для физического контроля доступа. Чистая
  функция-оценщик — [libs/black_ice_common/access_rules.py](libs/black_ice_common/access_rules.py).
  Подключено только к живому Kafka-пайплайну
  ([services/match/app/stream_consumer.py](services/match/app/stream_consumer.py)),
  не к `POST /identify` — только у пайплайна есть `camera_id` на кадр; статус
  в live-фиде теперь `ACCESS GRANTED`/`ACCESS DENIED` вместо голого
  `IDENTITY CONFIRMED`. Shadow-mode консьюмер осознанно НЕ пропущен через эту
  проверку (`access_check=None` по умолчанию в `evaluate_embedding`) — его
  задача сравнивать биометрию кандидат-модели, а не решения о доступе.
  CRUD `/access-rules` за новым RBAC-правом `access_rules` (только admin),
  страница в admin-ui. Проверено вживую: реальный API создал правило в
  реальном Postgres, `is_access_allowed` дал верный ответ по этим же данным,
  CASCADE-удаление правил при удалении identity подтверждено на реальном
  Postgres (не только sqlite). Окна через полночь (22:00–06:00) теперь тоже
  поддержаны: день недели правила — это день, когда смена *началась*, а не
  календарная дата в момент проверки, иначе "пятничное" ночное окно молча
  переставало бы совпадать в 2 часа ночи субботы. Тесты —
  `test_overnight_window_gates_access`/`test_overnight_window_weekday_matches_shift_start_day`
  в `tests/unit/test_access_rules.py`.
- ✅ Alerting (Milestone 4) — webhook-уведомления на бизнес/security-события,
  отдельно от инфра-алертов Prometheus (`observability/prometheus/alerts.yml`,
  latency/error-rate/drift — те никуда не делись). Новая модель `AlertRule`
  ([libs/black_ice_common/db.py](libs/black_ice_common/db.py)): `event_type`
  (`access_denied`/`camera_offline`) + опциональные identity/camera фильтры +
  `webhook_url`. Доставка — [libs/black_ice_common/alerting.py](libs/black_ice_common/alerting.py),
  в фоновом потоке, не блокирует hot path матчинга; недоступный webhook
  логируется и не роняет пайплайн. `access_denied` триггерится из
  `stream_consumer.py` сразу при отказе; `camera_offline` — новый скрипт
  [scripts/camera_offline_check.py](scripts/camera_offline_check.py)
  (K8s CronJob каждые 5 мин, `infra/k8s/black-ice/templates/camera-offline-cronjob.yaml`),
  т.к. staleness камеры никем больше не опрашивается. CRUD `/alert-rules` за
  RBAC-правом `alert_rules` (только admin), страница в admin-ui.
  **Реальный баг, пойманный именно live-проверкой**: скрипт-версия
  (camera_offline_check, короткоживущий процесс) изначально не дожидалась
  фоновых потоков доставки — daemon-поток убивается мгновенно при выходе
  процесса, так что алерты от CronJob'а реально никогда бы не отправились.
  Исправлено: `fire_alert` теперь возвращает список потоков, скрипт их
  join'ит перед выходом; у долгоживущего `stream_consumer` (сам процесс
  постоянно работает) эта проблема не стояла. Проверено вживую двумя
  способами: реальный HTTP-приёмник вебхуков получил оба типа события
  (`access_denied` и `camera_offline`) от реального пайплайна против
  реального Postgres/Qdrant.
  **Второй реальный баг, найденный тем же live-проходом, не связанный с
  Milestone 4 напрямую**: RBAC-переключение роли в admin-ui (login как admin
  → logout → login как operator, без перезагрузки страницы) показывало
  закэшированные строки из ПРЕДЫДУЩЕЙ admin-сессии под сообщением "нет
  доступа" — TanStack Query кэш не чистился при смене сессии. Тот же паттерн
  существовал и в Cameras/AccessRules/Identities/Audit (не только в новой
  AlertRules-странице). Исправлено в корне — `queryClient.clear()` при
  каждом `login()`/`logout()` в
  [admin-ui/src/contexts/AuthContext.tsx](admin-ui/src/contexts/AuthContext.tsx),
  а не патчем в каждой странице по отдельности.

## Инфраструктура

- ✅ CI (lint+test+build+helm-validate), сам workflow проверен `actionlint`
- ✅ Helm-чарт: `helm lint`+`helm template`+`kubeconform` против реальных схем k8s
- ✅ docker-compose валиден (`docker compose config`)
- ✅ **Kafka/redpanda на этом хосте — почищено**: `docker.redpanda.com/...` не
  качался стабильно с одной и той же ошибкой containerd
  (`failed to prepare extraction snapshot ... failed to stat parent: ... no
  such file or directory`) даже после полного сноса VM Docker Desktop. Не
  оверлей-баг сам по себе — реальная причина: диск хоста был забит образами
  от постороннего проекта (`bitbotby-*`, 15.6ГБ) плюс дублями/старым build
  cache этого репо (постоянно ~20ГБ лишнего), и каждый pull образа
  упирался в нехватку места посреди распаковки, что и ломало метаданные
  снапшотов containerd — раз за разом, независимо от того, сколько раз
  сбрасывать саму VM. Почищено `docker rmi`/`docker builder prune` (~35ГБ),
  после чего `docker pull docker.redpanda.com/redpandadata/redpanda:v24.2.7`
  и `docker compose up redpanda` отработали с первого раза.
- ⚠️ **Полный стек поднят частично вживую**: qdrant+postgres+match — по-настоящему,
  реальный enroll/identify/audit/reindex/нагрузочный тест (см.
  [PHASE0_RESULTS.md](PHASE0_RESULTS.md)). Redpanda теперь тоже поднимается и
  отвечает на этом хосте (см. выше), но полный end-to-end прогон
  ingest→detect→embed→match через реальную Kafka ещё не переделан после
  сброса VM (образы `infra-detect`/`infra-embed`/`infra-ingest` слетели
  вместе с ней и требуют пересборки) — отдельный шаг, не блокер этого фикса.

## Тесты

105/105 зелёных, против реальных моделей и реальной семантики Qdrant/Postgres, не моков.
Два реальных бага поймано именно real-verification методологией, оба невидимы
для sqlite по умолчанию:
- слишком узкий crop между detect/embed портил alignment
  ([tests/integration/test_detect_embed_handoff.py](tests/integration/test_detect_embed_handoff.py))
- `DELETE /identities/{id}` падал на реальном Postgres при наличии audit-истории
  (FK constraint, sqlite не проверяет их по умолчанию) — исправлено и теперь
  ловится тестом даже на sqlite, т.к. FK enforcement включён явно
  ([tests/integration/test_revoke_with_audit_history.py](tests/integration/test_revoke_with_audit_history.py))

## Дальше — что нужно для реального продукта

Не код, а: юридика/DPIA под биометрию, bias/fairness-тестирование на реальных данных,
пентест, обученная антиспуфинг-модель.
Docker-compose стек вживую — сделано (см. [PHASE0_RESULTS.md](PHASE0_RESULTS.md)),
Kafka/redpanda на этом хосте теперь тоже поднимается (см. "Инфраструктура" выше).

- ✅ **Реальный IdP** — было в списке выше, теперь сделано и вычеркнуто. Полное
  описание, включая как проверялось (curl + реальный браузерный логин через
  admin-ui), — см. [README.md's "Реальный IdP (Keycloak)"](README.md#реальный-idp-keycloak).
  Коротко: `AUTH_BACKEND=oidc` (opt-in, дефолт `api_key` не тронут) заставляет
  `require()`/`/auth/login` проверять `Authorization: Bearer <JWT>` против
  реального Keycloak вместо `X-API-Key` — [libs/black_ice_common/oidc.py](libs/black_ice_common/oidc.py),
  роль берётся из `realm_access.roles` токена, сверяется с тем же `rbac.ROLES`,
  что и раньше. admin-ui получил настоящий Authorization Code + PKCE через
  `keycloak-js` вместо формы с API-ключом (`VITE_AUTH_MODE=oidc`).
- ✅ **HA/DR** — было в списке выше, теперь сделано и вычеркнуто. Бэкап/рестор для
  обоих stateful-хранилищ: Postgres через [scripts/backup_postgres.py](scripts/backup_postgres.py)
  (`pg_dump -Fc`, кастомный формат — сжатый, поддерживает выборочный/параллельный
  restore) и [scripts/restore_postgres.py](scripts/restore_postgres.py)
  (`pg_restore --clean --if-exists`, сознательно деструктивный); Qdrant через
  [scripts/backup_qdrant.py](scripts/backup_qdrant.py) (снапшот коллекции за
  алиасом + скачивание файла на диск — снапшот, оставленный в директории самого
  Qdrant, не бэкап, т.к. живёт на том же volume, что и коллекция) и
  [scripts/restore_qdrant.py](scripts/restore_qdrant.py) (заливка снапшота в
  свежую коллекцию + атомарный alias-swap, тот же паттерн, что у
  `reindex_faces.py` — читатели/писатели никогда не видят наполовину
  восстановленную коллекцию). K8s CronJob
  ([backup-cronjob.yaml](infra/k8s/black-ice/templates/backup-cronjob.yaml)) гоняет
  оба бэкапа на общий PVC
  ([backup-pvc.yaml](infra/k8s/black-ice/templates/backup-pvc.yaml)).
  Юнит-тесты (31 шт, `tests/unit/test_backup_postgres.py`+`test_backup_qdrant.py`)
  мокают `subprocess`/HTTP — как и везде в этом репо, CI (`tests/unit`+`tests/integration`)
  гоняется против throwaway sqlite/in-memory Qdrant без реальных сервисов, так
  что честная проверка живого round-trip'а не может быть частью CI-теста, только
  ручная. Сделана: реальный Postgres — засеяна строка, бэкап, порча данных,
  restore, проверено содержимое вернулось к состоянию до бэкапа (не просто "код
  выполнился без ошибок"). Реальный Qdrant — то же самое с вектором и его payload
  через alias `faces`, включая проверку, что alias после restore реально
  переключился на новую коллекцию. Оба прогона — через уже собранный
  `infra-match:latest` (тот же образ, что использует CronJob), не с хоста, т.к.
  `pg_dump`/`pg_restore` на хосте не установлены — ещё одна причина, почему это
  не может быть автоматическим CI-тестом без поднятия реальных контейнеров.

- ✅ **Секреты в Vault** — было в списке выше, теперь сделано и вычеркнуто.
  `DATABASE_URL`/`BLACK_ICE_API_KEYS` больше не обязаны жить в plaintext
  env vars / Helm `values.yaml`. Новый резолвер
  [libs/black_ice_common/secrets.py](libs/black_ice_common/secrets.py):
  `VAULT_ADDR`/`VAULT_TOKEN` не заданы (дефолт для compose/локальной
  разработки) → падает обратно на обычный env var/дефолт, без Vault не
  нужен вообще. Задан → читает секрет из Vault KV v2 через обычный
  `requests.get` (без клиента `hvac` — уже зависим от requests, а чтение
  KV v2 это один GET). `config.py` переопределяет `database_url` через
  резолвер сразу после конструирования `Settings()`; `rbac.py`'s
  `seed_from_env` — так же для `BLACK_ICE_API_KEYS`.
  Helm-чарт: `vault.enabled` в `values.yaml` — когда включён, `secret.yaml`
  вообще не рендерит plaintext `Secret` (проверено `helm template`,
  реально ничего не выводится), а `match`-деплоймент и все 3 CronJob'а
  получают `VAULT_TOKEN` из ВНЕШНЕГО `Secret` (`vaultTokenSecretRef`) —
  чарт сознательно не создаёт и не хранит сам токен, иначе это была бы та
  же проблема с plaintext-секретом, просто в другом месте.
  Проверено вживую по-настоящему: поднят реальный `hashicorp/vault` в
  dev-режиме (`docker compose --profile secrets up vault`), туда записан
  реальный `DATABASE_URL`/`BLACK_ICE_API_KEYS` через `vault kv put`, match
  запущен БЕЗ единого plaintext-секрета в окружении (только
  `VAULT_ADDR`/`VAULT_TOKEN`) — подключился к правильной БД, засеял
  Vault-ключ, и **отверг** старый статичный `dev-admin-key` (401) — то есть
  не тихо продолжал принимать старые ключи в обход Vault. Helm-путь
  проверен `helm lint`+`helm template --set vault.enabled=true` (реальный
  установленный `helm`, не просто "выглядит правильно") — подтверждено,
  что `Secret`-объект не рендерится и все 4 workload'а вместо этого берут
  `envFrom` из `vaultTokenSecretRef`.
