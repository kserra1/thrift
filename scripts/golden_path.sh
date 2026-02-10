#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-thrift}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
MODEL_NAME="${MODEL_NAME:-iris}"
MODEL_VERSION="${MODEL_VERSION:-v1}"
REDIS_DEPLOY="${REDIS_DEPLOY:-redis}"

usage() {
  cat <<EOF
Golden Path Test

Environment variables:
  NAMESPACE     Kubernetes namespace (default: thrift)
  GATEWAY_URL   Gateway base URL (default: http://localhost:8080)
  MODEL_NAME    Model name (default: iris)
  MODEL_VERSION Model version (default: v1)
  REDIS_DEPLOY  Redis deployment name (default: redis)

Requires:
  - kubectl access to cluster
  - Gateway reachable at GATEWAY_URL

Example:
  NAMESPACE=thrift GATEWAY_URL=http://localhost:8080 ./scripts/golden_path.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

echo "== Golden Path Test =="
echo "Namespace: ${NAMESPACE}"
echo "Gateway:   ${GATEWAY_URL}"
echo "Model:     ${MODEL_NAME}:${MODEL_VERSION}"
echo

echo "1) Clear Redis assignment"
kubectl -n "${NAMESPACE}" exec "deploy/${REDIS_DEPLOY}" -- redis-cli DEL "model:${MODEL_NAME}:${MODEL_VERSION}" >/dev/null || true

echo "2) Predict (auto-load path)"
PREDICT_RESP=$(curl -sS -X POST "${GATEWAY_URL}/models/${MODEL_NAME}/versions/${MODEL_VERSION}/predict" \
  -H "Content-Type: application/json" \
  -d '{"features":[5.1,3.5,1.4,0.2]}')
echo "Predict response: ${PREDICT_RESP}"

echo "3) Verify Redis assignment exists"
ASSIGNED_WORKER=$(kubectl -n "${NAMESPACE}" exec "deploy/${REDIS_DEPLOY}" -- redis-cli GET "model:${MODEL_NAME}:${MODEL_VERSION}" | tr -d '\r')
if [[ -z "${ASSIGNED_WORKER}" ]]; then
  echo "ERROR: Redis assignment missing"
  exit 1
fi
echo "Assigned worker: ${ASSIGNED_WORKER}"

echo "4) Global unload"
UNLOAD_RESP=$(curl -sS -X POST "${GATEWAY_URL}/models/unload" \
  -H "Content-Type: application/json" \
  -d "{\"model_name\":\"${MODEL_NAME}\",\"version\":\"${MODEL_VERSION}\"}")
echo "Unload response: ${UNLOAD_RESP}"

echo "5) Verify Redis assignment cleared"
ASSIGNED_WORKER_AFTER=$(kubectl -n "${NAMESPACE}" exec "deploy/${REDIS_DEPLOY}" -- redis-cli GET "model:${MODEL_NAME}:${MODEL_VERSION}" | tr -d '\r')
if [[ -n "${ASSIGNED_WORKER_AFTER}" ]]; then
  echo "ERROR: Redis assignment still present: ${ASSIGNED_WORKER_AFTER}"
  exit 1
fi
echo "Redis assignment cleared"

echo
echo "Golden Path Test PASSED"
