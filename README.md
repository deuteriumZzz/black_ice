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
- Netrunner UI: `http://localhost:8080`
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
| `GET /health`, `GET /metrics` | — | |
| `WS /ws/live` | — | живой терминальный фид для UI, питается из Kafka-потока embed→match |

Авторизация — `X-API-Key` → роль, настраивается через `BLACK_ICE_API_KEYS=key:role,...`
(дефолтные dev-ключи: `dev-admin-key`, `dev-operator-key`).

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
- **Параметры HNSW/шардов не проверены на настоящем Qdrant-сервере**:
  механика переключения алиаса при re-index полностью протестирована; реальный
  эффект кастомных `m`/`ef_construct`/числа шардов на recall/латентность —
  нет, потому что local/embedded-режим Qdrant их молча игнорирует. См. раздел
  Observability.
- **Liveness / template protection**: у liveness теперь есть настоящая точка
  подключения обученной модели, но сама обученная модель не поставляется (см.
  раздел Security); model-inversion/template-protection — по-прежнему только
  осведомлённость, не реализация.

## Структура репозитория

```
black-ice/
├── services/{ingest,detect,embed,match,tracking}/  — код каждого этапа + Dockerfile
├── libs/black_ice_common/                          — общий код: config/schemas/kafka/ml/rbac/tracing
├── infra/{docker-compose.yml,k8s/black-ice/}        — compose-стек + Helm-чарт
├── observability/{prometheus,grafana}/              — конфиг скрейпа, алерты, дашборды
├── ml/eval/                                         — калибровка ROC/FAR-FRR
├── ui/index.html                                    — netrunner-стилизованный живой терминал + ручной скан
├── scripts/                                         — фетч демо-кадров, чистка по retention, reindex, отчёты drift/shadow
├── tests/{unit,integration,load}/
└── .github/workflows/ci.yml                         — lint, тесты, сборка каждого образа, helm lint+validate
```
