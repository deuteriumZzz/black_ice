# BLACK ICE

Face-recognition access-control pipeline, styled after Cyberpunk 2077's ICE —
defensive access-control semantics, netrunner-terminal aesthetic in the UI. Built
against `BLACK_ICE_spec.md`'s full roadmap: monolith → message-driven services →
Kubernetes → observability → security/compliance hardening.

## Architecture

```
ingest (1 pod/camera) --frames.raw--> detect (consumer group) --faces.detected--> embed (consumer group) --faces.embedded--> match (API + consumer)
                                          |                                                                                       |
                                    tracking lib (norfair)                                                          Qdrant (search) + Postgres (audit/identities)
```

Kafka protocol via Redpanda (single binary, no Zookeeper — same `confluent-kafka`
client code as a real Kafka cluster; swap the bootstrap server in prod). See
[services/](services) for each stage, [libs/black_ice_common](libs/black_ice_common)
for the shared detection/embedding/tracing/RBAC code every service imports.

### Why detection and embedding are split into separate services

`FaceAnalysis.get()` asserts a detection model is loaded and always runs every
model in the pack — exactly the coupling stage 2 needs to avoid so the CPU-bound
detector and the (GPU-bound in prod) embedder can scale independently. Both load
their single ONNX file directly via `insightface.model_zoo` instead
([libs/black_ice_common/detection.py](libs/black_ice_common/detection.py),
[embedding.py](libs/black_ice_common/embedding.py)).

### The GIL problem (spec 3.1)

All-Python stack, so the unit of horizontal scale is the **process/pod**, not a
thread: ingest is one OS process per camera; detect/embed/match scale by adding
pods to their Kafka consumer group (`docker compose up --scale detect=3`, or the
Helm chart's `detect.replicas`/HPA). No CPU-bound work runs inside an asyncio
event loop.

### Frame sampling + tracking (spec 4)

`services/tracking/tracker.py` runs an IoU/Kalman tracker (norfair) per camera.
Detection still runs every frame (cheap); what's actually throttled is
**embedding** (expensive) — a track is only forwarded to embed on its first frame
and every `embed_interval_frames` after that. See
[tests/unit/test_tracker.py](tests/unit/test_tracker.py).

### Distributed tracing across a Kafka hop

HTTP gets trace context for free from FastAPI's OTel instrumentor; a Kafka
message doesn't. `libs/black_ice_common/tracing.py` injects/extracts the W3C
`traceparent` through Kafka message headers by hand, so one camera frame's whole
journey (ingest → detect → embed → match) shows up as a single trace in Jaeger.
Verified in [tests/unit/test_tracing.py](tests/unit/test_tracing.py).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r services/match/requirements.txt   # or any one service's requirements.txt
python scripts/fetch_demo_frames.py               # populates a demo frame from InsightFace's own test data

cd infra
docker compose up --build              # core pipeline: redpanda, qdrant, postgres, ingest(demo), detect, embed, match, ui
docker compose --profile observability up -d   # + prometheus, grafana, jaeger
```

- Match API: `http://localhost:8000` (docs at `/docs`, metrics at `/metrics`)
- Netrunner UI: `http://localhost:8080`
- Grafana: `http://localhost:3000` (anonymous admin) · Prometheus: `:9090` · Jaeger: `:16686`

Demo mode (`SOURCE=demo` on ingest) loops a single bundled test image as a fake
camera feed — no webcam/RTSP source needed to see the whole pipeline run. Point
`SOURCE` at `0` (webcam) or an `rtsp://` URL for a real feed.

### API

| Endpoint | Role | Notes |
|---|---|---|
| `POST /enroll` | admin | `name`, `consent=true`, `file`; optional `identity_id` to add another sample to an existing identity (spec: multi-embedding per identity) |
| `POST /identify` | operator, admin | returns `IDENTITY CONFIRMED` / `IDENTITY UNKNOWN` (open-set — never "closest guess") |
| `GET /audit` | admin | recent access-decision log |
| `DELETE /identities/{id}` | admin | consent revocation / right to erasure — removes the identity row and every embedding under it |
| `GET /health`, `GET /metrics` | — | |
| `WS /ws/live` | — | live terminal feed for the UI, fed by the embed→match Kafka stream |

Auth is `X-API-Key` → role, configured via `BLACK_ICE_API_KEYS=key:role,...`
(default dev keys: `dev-admin-key`, `dev-operator-key`).

```bash
curl -F "name=Neo" -F "consent=true" -F "file=@face.jpg" -H "X-API-Key: dev-admin-key" http://localhost:8000/enroll
curl -F "file=@face.jpg" -H "X-API-Key: dev-operator-key" http://localhost:8000/identify
```

## Test

```bash
pip install -r services/match/requirements.txt pytest
python scripts/fetch_demo_frames.py
python -m pytest tests/unit tests/integration -q
```

No Kafka/Postgres/Qdrant needed for the test suite — unit tests exercise pure
logic (decision, tracker, tracing propagation, ROC/FAR-FRR math), integration
tests run the real ONNX models against a bundled sample face and the match API
against sqlite + in-memory Qdrant. All verified against real data, not mocks —
including a regression test
([tests/integration/test_detect_embed_handoff.py](tests/integration/test_detect_embed_handoff.py))
for a real bug caught during development: too tight a crop margin between
detect and embed silently degraded embedding quality (cosine similarity 0.97
instead of >0.999) by clipping ArcFace's alignment warp.

Load test: `locust -f tests/load/locustfile.py --host http://localhost:8000`.

## Kubernetes / Helm

```bash
helm lint infra/k8s/black-ice
helm template black-ice infra/k8s/black-ice | less
helm install black-ice infra/k8s/black-ice -f my-values.yaml
```

Stateful dependencies (Kafka, Qdrant, Postgres) are **not** bundled in this
chart — install them via their own official charts and point `values.yaml`'s
`connections.*` at them. Bundling stateful infra into an app chart is the
coupling that makes upgrades and backups painful. Verified offline (no cluster
available in dev) via `helm lint` + `helm template` + `kubeconform -strict`
against real Kubernetes OpenAPI schemas, across default values, GPU-enabled
embed, multi-camera ingest, and HPA-disabled configurations.

`detect`/`embed`/`match` each have an HPA on CPU. `ingest` is one Deployment per
camera (`values.yaml`'s `ingest.cameras` list) — never scaled by replica count,
per the GIL note above. A `CronJob` runs the retention sweep
([scripts/purge_expired.py](scripts/purge_expired.py)) daily.

## Observability

Prometheus scrapes each service's `/metrics` (custom counters/histograms in
[libs/black_ice_common/metrics.py](libs/black_ice_common/metrics.py)); Grafana
dashboard auto-provisioned (frames/detections/embeddings per second, access
decisions, p99 latency per stage); Jaeger for the distributed traces described
above; [observability/prometheus/alerts.yml](observability/prometheus/alerts.yml)
alerts on p99 latency, match error rate (circuit breaker tripped), a dead
ingest feed, and drift (below). Rules validated with `promtool check rules/config`.

### Drift monitoring

Production has no ground truth to check accuracy against, so
[scripts/drift_report.py](scripts/drift_report.py) watches a proxy: a two-sample
Kolmogorov-Smirnov test between a baseline and a recent window of confirmed
match scores from the audit log. A significant shift means *something* changed
(model, population, camera/lighting, a stale gallery) — it flags, it doesn't
diagnose. Pushes to Prometheus Pushgateway (`docker compose --profile
observability up`, or the Helm chart's `driftMonitorCronJob`, hourly by
default) since a CronJob doesn't live long enough to be scraped directly. Pure
statistics tested with synthetic distributions
([tests/unit/test_drift_report.py](tests/unit/test_drift_report.py)); the
window-query logic tested against a real (sqlite) audit log
([tests/integration/test_drift_report_db.py](tests/integration/test_drift_report_db.py)).

### Zero-downtime re-index / re-shard

`collection_name` in Qdrant is an **alias**, not a collection — upsert/search
calls always go through the alias, and Qdrant resolves it server-side.
[scripts/reindex_faces.py](scripts/reindex_faces.py) creates a new concrete
collection with different HNSW (`--m`/`--ef-construct`) or shard-count
(`--shards`) parameters, copies every point across, then atomically repoints
the alias — readers and writers never see a moment where it points at nothing.
Verified end-to-end against Qdrant's local mode: alias resolution, point
migration, and post-swap writes
([tests/integration/test_reindex.py](tests/integration/test_reindex.py)).
Honest caveat: Qdrant's embedded/local mode silently ignores custom HNSW
params (always reports its defaults) and always does brute-force search
regardless of `search_params` — the *alias-swap mechanics* are verified, the
actual recall/latency effect of `hnsw_m`/`hnsw_ef_construct`/`hnsw_ef_search`
needs a real Qdrant server to observe.

### Shadow-mode model deploy

Evaluates a candidate embedding model against live traffic before promoting
it — never affects the real access decision. A different model has a
different embedding space, so this isn't a single side-by-side comparison:
`SHADOW_EMBEDDING_ENABLED=true` makes `/enroll` write into *both* the primary
gallery and a separate `faces_shadow` gallery (via the candidate model,
default `buffalo_s` — a smaller/faster InsightFace pack, a realistic
"should we downgrade to the cheaper model" evaluation), and the embed worker
publishes a parallel embedding to `faces.embedded.shadow`. A dedicated
consumer ([services/match/app/shadow_consumer.py](services/match/app/shadow_consumer.py))
searches the shadow gallery and logs to the same `audit_log` table tagged
`model_version=<pack>`, correlated by `(frame_id, track_id)` — its own
CircuitBreaker means a broken candidate model can never degrade the primary
path. [scripts/shadow_report.py](scripts/shadow_report.py) joins primary vs.
shadow decisions on that key and reports the agreement rate before you'd
promote the candidate. Full pipeline verified — dual-gallery enrollment, a
shadow decision correctly logged without touching the primary audit trail
([tests/integration/test_shadow_mode.py](tests/integration/test_shadow_mode.py)),
and the agreement-rate math against synthetic agree/disagree cases
([tests/integration/test_shadow_report.py](tests/integration/test_shadow_report.py)).

## Security & compliance

- **RBAC**: static API-key → role mapping ([libs/black_ice_common/rbac.py](libs/black_ice_common/rbac.py)).
  ponytail: no real IdP — swap for OIDC/JWT once there's an actual identity provider.
- **Rate limiting**: slowapi, per-route, default 30/min.
- **Circuit breaker**: pybreaker around the Qdrant/Postgres calls on the stream
  consumer — fails fast instead of piling up latency when a dependency is down.
- **Consent + retention**: `/enroll` requires `consent=true`; every identity gets
  a `retention_expires_at`; the CronJob purges both the Postgres row and every
  Qdrant vector for expired identities.
- **Audit log**: every access decision (matched/unmatched, score, requester
  role, camera) — deliberately keyed by `identity_id`, not biometric data, so it
  stays meaningful after an identity is purged.
- **Open-set recognition**: below `MATCH_THRESHOLD`, the answer is `UNKNOWN`,
  never "closest guess."
- **Liveness**: [libs/black_ice_common/liveness.py](libs/black_ice_common/liveness.py)
  has two layers. (1) A classical multi-signal heuristic — Laplacian sharpness +
  YCrCb chroma-variance ("color-texture analysis", the same family real
  anti-spoofing literature uses), still genuinely just a heuristic: catches a
  flat printed-photo or screen replay, nothing more. (2) `LivenessOnnxEngine`, a
  real plug-in point for a *trained* classifier via the project's existing
  onnxruntime dependency — set `LIVENESS_ONNX_MODEL_PATH` to a converted
  checkpoint (e.g. MiniFASNet/Silent-Face-Anti-Spoofing exported to ONNX) to use
  it instead of the heuristic. No such model ships here: the obvious
  off-the-shelf option (`deepface`'s bundled anti-spoofing) drags in
  TensorFlow+Keras+pandas as new hard dependencies and breaks this project's
  pinned `numpy<2`/onnxruntime-only stack — confirmed by actually trying it
  during development, not assumed. The plug-in's plumbing (preprocessing,
  inference, output parsing) is verified against a hand-built toy ONNX model
  ([tests/unit/test_liveness.py](tests/unit/test_liveness.py)), independent of
  any specific trained checkpoint. Off by default
  (`LIVENESS_CHECK_ENABLED=false`) — the heuristic path has a real false-reject
  rate on low-quality webcams.
- **Model-inversion awareness**: only 512-d embeddings and short-lived JPEG crops
  cross the wire/get logged — no raw enrollment photos are persisted anywhere.
  Embeddings themselves are still invertible in principle (model-inversion
  attacks against face embeddings are an active research area); template
  protection (e.g. cancelable biometrics, homomorphic-encrypted templates) is
  not implemented here — noted as the next hardening step, not solved.

## Calibration (FAR/FRR, ROC/DET)

```bash
pip install -r ml/eval/requirements.txt
python ml/eval/roc_calibration.py --dataset /path/to/lfw-style/dataset --out roc.png
```

Computes genuine/impostor cosine-similarity distributions, prints the
equal-error-rate threshold, plots ROC + DET curves. The FAR/FRR/EER math itself
is unit-tested against synthetic well-separated and overlapping distributions
([tests/unit/test_roc_calibration.py](tests/unit/test_roc_calibration.py))
independent of any real dataset.

## What's simplified (and the upgrade path)

- **Alembic**: schema managed via `create_all()`; add real migrations once the
  schema needs to evolve under live data.
- **GPU/TensorRT**: everything runs on `CPUExecutionProvider`; swap the ONNX
  Runtime provider (and the Helm `embed.gpu.enabled` flag, already wired) once
  there's a GPU node pool.
- **Message schemas**: plain JSON, not Avro + schema registry — add one if a
  second consumer language or real schema evolution shows up.
- **Tracking is a library, not a service**: `services/tracking/tracker.py` runs
  in-process inside `detect` rather than its own Kafka-hop microservice — it
  needs tight per-camera frame-to-frame state, which a network hop would only
  slow down.
- **HNSW/shard params unverified against a real Qdrant server**: the alias-swap
  re-index mechanics are fully tested; the actual recall/latency effect of
  custom `m`/`ef_construct`/shard count isn't, since Qdrant's local/embedded
  mode silently ignores them. See the Observability section.
- **Liveness / template protection**: liveness has a real trained-model plug-in
  point now, but no shipped trained model (see Security section); model-
  inversion/template-protection is still awareness-only, not implemented.

## Repo layout

```
black-ice/
├── services/{ingest,detect,embed,match,tracking}/  — per-stage code + Dockerfile
├── libs/black_ice_common/                          — shared config/schemas/kafka/ml/rbac/tracing
├── infra/{docker-compose.yml,k8s/black-ice/}        — compose stack + Helm chart
├── observability/{prometheus,grafana}/              — scrape config, alerts, dashboards
├── ml/eval/                                         — ROC/FAR-FRR calibration
├── ui/index.html                                    — netrunner-styled live terminal + manual scan
├── scripts/                                         — demo-frame fetch, retention purge, reindex, drift/shadow reports
├── tests/{unit,integration,load}/
└── .github/workflows/ci.yml                         — lint, test, build every service image, helm lint+validate
```
