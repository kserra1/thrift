import http from "k6/http";
import { check, sleep } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.GATEWAY_URL || "http://localhost:8080";
const MODEL = __ENV.MODEL || "iris";
const VERSION = __ENV.VERSION || "v1";
const SAMPLE_FEATURES = __ENV.FEATURES_JSON
  ? JSON.parse(__ENV.FEATURES_JSON)
  : [5.1, 3.5, 1.4, 0.2];

export const options = {
  stages: [
    { duration: "30s", target: 10 },
    { duration: "2m", target: 25 },
    { duration: "2m", target: 50 },
    { duration: "2m", target: 0 }
  ],
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<500"],
    http_200_rate: ["rate>0.98"]
  }
};

const httpStatusCount = new Counter("http_status_count");
const http200Rate = new Counter("http_200_rate");
const httpErrorCount = new Counter("http_error_count");

export default function () {
  const url = `${BASE_URL}/models/${MODEL}/versions/${VERSION}/predict`;
  const payload = JSON.stringify({ features: SAMPLE_FEATURES });
  const params = { headers: { "Content-Type": "application/json" } };

  const res = http.post(url, payload, params);
  httpStatusCount.add(1, { status: String(res.status) });
  if (res.status === 200) {
    http200Rate.add(1);
  } else {
    httpErrorCount.add(1, { status: String(res.status) });
    if (Math.random() < 0.01) {
      console.error(`non-200 ${res.status}: ${res.body}`);
    }
  }
  check(res, {
    "status is 200": (r) => r.status === 200
  });

  sleep(0.1);
}
