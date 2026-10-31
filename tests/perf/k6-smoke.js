import http from 'k6/http';
import { check } from 'k6';
// Week-0 stub: GET /health baseline. Run: k6 run tests/perf/k6-smoke.js
export const options = { vus: 5, duration: '30s' };
export default function () {
  const r = http.get(`${__ENV.BASE_URL || 'http://localhost:8010'}/health`);
  check(r, { 'health 200': (x) => x.status === 200 });
}
