import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.GATEWAY_URL || "http://localhost:8080";
const MODEL = __ENV.MODEL || "iris";
const VERSION = __ENV.VERSION || "v1";

export const options = {
  stages: [
    { duration: "15s", target: 10 },
    { duration: "15s", target: 100 },
    { duration: "30s", target: 100 },
    { duration: "30s", target: 10 },
    { duration: "15s", target: 0 }
  ],
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<800"]
  }
};

export default function () {
  const url = `${BASE_URL}/models/${MODEL}/versions/${VERSION}/predict`;
  const payload = JSON.stringify({ features: [5.1, 3.5, 1.4, 0.2] });
  const params = { headers: { "Content-Type": "application/json" } };

  const res = http.post(url, payload, params);
  check(res, {
    "status is 200": (r) => r.status === 200
  });
  sleep(0.05);
}
