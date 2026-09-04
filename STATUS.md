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

## Инфраструктура

- ✅ CI (lint+test+build+helm-validate), сам workflow проверен `actionlint`
- ✅ Helm-чарт: `helm lint`+`helm template`+`kubeconform` против реальных схем k8s
- ✅ docker-compose валиден (`docker compose config`)
- ⚠️ **Полный стек поднят частично вживую**: qdrant+postgres+match — по-настоящему,
  реальный enroll/identify/audit/reindex/нагрузочный тест (см.
  [PHASE0_RESULTS.md](PHASE0_RESULTS.md)). Kafka/redpanda заблокирован повреждением
  containerd на конкретном Docker Desktop хосте (не код-баг — задокументировано,
  чинится либо полным сбросом Docker Desktop, либо на другой машине)

## Тесты

43/43 зелёных, против реальных моделей и реальной семантики Qdrant/Postgres, не моков.
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
реальный IdP вместо статичных ключей, секреты в Vault, пентест, HA/DR, обученная
антиспуфинг-модель. Docker-compose стек вживую — сделано (см.
[PHASE0_RESULTS.md](PHASE0_RESULTS.md)), кроме Kafka-пайплайна, упёршегося в
повреждённый Docker Desktop на этой машине — нужен чистый Docker-хост.
