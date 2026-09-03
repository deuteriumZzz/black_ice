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

## Качество распознавания

- ✅ Калибровка FAR/FRR, ROC/DET-кривая — [ml/eval/roc_calibration.py](ml/eval/roc_calibration.py)
  ⚠️ математика протестирована на синтетике, ни разу не гонялась на реальном датасете лиц
- ✅ Open-set recognition — ниже порога всегда `UNKNOWN`, не "похоже на"
- ✅ Multi-embedding per identity — `/enroll` с `identity_id` добавляет ещё один сэмпл

## Масштабируемость

- ✅ ANN-индекс (Qdrant HNSW), настраиваемые `hnsw_m`/`ef_construct`/`ef_search`
  ⚠️ параметры не проверены на реальном сервере (local-режим Qdrant их игнорирует)
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
- ✅ Role-based access — API-key → роль (admin/operator/viewer)

## Netrunner UI

- ✅ [ui/index.html](ui/index.html) — терминальный стиль, live-фид через WebSocket, ручной enroll/identify

## Инфраструктура

- ✅ CI (lint+test+build+helm-validate), сам workflow проверен `actionlint`
- ✅ Helm-чарт: `helm lint`+`helm template`+`kubeconform` против реальных схем k8s
- ✅ docker-compose валиден (`docker compose config`)
- ❌ **Полный стек ни разу не поднимался целиком** — в этой среде нет Docker-демона;
  каждый сервис проверен отдельно (реальные ONNX-модели, sqlite+in-memory Qdrant
  вместо Postgres/Qdrant), но `docker compose up --build` на всём разом — не проверялось

## Тесты

35/35 зелёных, против реальных моделей и реальной семантики Qdrant/Postgres, не моков.
Включая пойманный по ходу реальный баг (слишком узкий crop между detect/embed портил
alignment — [tests/integration/test_detect_embed_handoff.py](tests/integration/test_detect_embed_handoff.py)).

## Дальше — что нужно для реального продукта

Не код, а: юридика/DPIA под биометрию, bias/fairness-тестирование на реальных данных,
реальный IdP вместо статичных ключей, секреты в Vault, пентест, HA/DR, обученная
антиспуфинг-модель, и — первым делом — прогнать весь docker-compose стек вживую.
