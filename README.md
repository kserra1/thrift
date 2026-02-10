# Thrift ML Serving Platform

Kubernetes-based ML model serving with a Spring Cloud Gateway that routes prediction requests to FastAPI workers based on which worker has a model loaded. Redis tracks model placement. Workers can auto-load on first request.

## Why It Exists

This project is an experiment in building a scalable serving layer for ML models. It focuses on:
- Dynamic routing to the worker that already has the model in memory.
- On-demand model loading with Redis-backed placement.
- Observability and load testing to understand bottlenecks early.

## Architecture (High Level)

- Gateway (Spring Cloud Gateway)
- Workers (FastAPI + model manager)
- Registry (Redis)
- Storage (Postgres + MinIO)
- Observability (Prometheus + Grafana)

Data flow:
- Client sends `POST /models/{model}/versions/{version}/predict` to the Gateway.
- Gateway consults Redis to find a worker that has the model loaded.
- If missing, Gateway triggers a load on a worker and updates Redis.
- Gateway proxies the request to that worker and returns the response.

## Repository Layout

- `gateway/` Spring Boot + Spring Cloud Gateway service
- `workers/` FastAPI worker service
- `k8s/` Kubernetes manifests for all services
- `docker-compose.yml` Local dev stack
- `loadtests/` k6 load test scripts
- `scripts/` utility scripts for model registration and golden path checks
- `prometheus/` Prometheus config
- `grafana/` dashboard and provisioning
- `models/` training scripts and sample models

## Core API (via Gateway)

- Predict: `POST /models/{model}/versions/{version}/predict`
- Load: `POST /models/load`
- Global unload: `POST /models/unload`

Example predict:
```bash
curl -sS -X POST http://localhost:8080/models/iris/versions/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"features":[5.1,3.5,1.4,0.2]}'
```

Example load:
```bash
curl -sS -X POST http://localhost:8080/models/load \
  -H "Content-Type: application/json" \
  -d '{"model_name":"iris","version":"v1","batch_size":32,"batch_wait_ms":50}'
```

Example unload:
```bash
curl -sS -X POST http://localhost:8080/models/unload \
  -H "Content-Type: application/json" \
  -d '{"model_name":"iris","version":"v1"}'
```

## Quickstart (Docker Compose)

Prereqs:
- Docker + Docker Compose

Run:
```bash
docker compose up --build
```

Gateway:
- `http://localhost:8080`

Grafana:
- `http://localhost:3000` (admin / admin)

Prometheus:
- `http://localhost:9090`

## Kubernetes Deploy

Prereqs:
- `kubectl` configured to your cluster
- Images built and available to the cluster

Create namespace and core services:
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/minio.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/prometheus.yaml
kubectl apply -f k8s/grafana.yaml
```

Deploy workers and gateway:
```bash
kubectl apply -f k8s/worker.yaml
kubectl apply -f k8s/gateway.yaml
```

Port-forward gateway:
```bash
kubectl -n thrift port-forward deploy/gateway 8080:8080
```

## Golden Path Test

This validates:
- Auto-load on predict
- Redis assignment
- Global unload
- Redis cleanup

Run:
```bash
./scripts/golden_path.sh
```

Optional env vars:
```bash
NAMESPACE=thrift \
GATEWAY_URL=http://localhost:8080 \
MODEL_NAME=iris \
MODEL_VERSION=v1 \
REDIS_DEPLOY=redis \
./scripts/golden_path.sh
```

## Model Registry Notes

- Redis keys are `model:{name}:{version}`.
- Auto-load happens if no Redis assignment exists.
- Global unload removes a model from all workers that currently have it.

## Performance Tuning (Workers)

Environment variables:
- `UVICORN_WORKERS` (default: 1)
- `DEFAULT_BATCH_SIZE` (default: 32)
- `DEFAULT_BATCH_WAIT_MS` (default: 50)
- `OMP_NUM_THREADS` and `MKL_NUM_THREADS` (recommend 1 when using multiple workers)

## Load Testing (k6)

Run:
```bash
k6 run loadtests/k6_predict.js
```

Other profiles:
```bash
k6 run loadtests/k6_spike.js
k6 run loadtests/k6_soak.js
```

Override defaults:
```bash
GATEWAY_URL=http://localhost:8080 \
MODEL=iris \
VERSION=v1 \
k6 run loadtests/k6_predict.js
```

Custom features:
```bash
FEATURES_JSON='[5.1,3.5,1.4,0.2]' \
MODEL=iris VERSION=v1 k6 run loadtests/k6_predict.js
```

## Larger Model Workflow (Digits)

Train and register a heavier model:
```bash
python models/train_digits_rf.py
python scripts/register_model.py --model-path digits_v1.pkl --name digits --version v1
```

Load and test:
```bash
curl -sS -X POST http://localhost:8080/models/load \
  -H "Content-Type: application/json" \
  -d '{"model_name":"digits","version":"v1","batch_size":32,"batch_wait_ms":10}'

MODEL=digits VERSION=v1 k6 run loadtests/k6_predict.js
MODEL=digits VERSION=v1 k6 run loadtests/k6_spike.js
MODEL=digits VERSION=v1 k6 run loadtests/k6_soak.js
```

Optional custom features for digits:
```bash
FEATURES_JSON='[0,0,5,13,9,1,0,0,0,0,13,15,10,15,5,0,0,3,15,2,0,11,8,0,0,4,12,0,0,8,8,0,0,5,8,0,0,9,8,0,0,4,11,0,1,12,7,0,0,2,14,5,10,12,0,0,0,0,6,13,10,0,0,0]' \
MODEL=digits VERSION=v1 k6 run loadtests/k6_predict.js
```

## Observability

- Gateway adds `X-Request-ID` on all requests and propagates it to workers.
- Workers include `X-Request-ID` in responses and logs.
- Prometheus scrapes metrics and Grafana dashboards visualize latency, errors, and load.

## Troubleshooting

- `404 Model not loaded`: run `/models/load` or confirm Redis assignment exists.
- `503 No healthy workers`: check worker health endpoints and readiness.
- `Empty reply from server`: check gateway pod logs and routing filter configuration.


