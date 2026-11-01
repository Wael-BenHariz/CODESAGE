export const optionsByScenario = {
  smoke: { vus: 1, duration: '30s', thresholds: { http_req_failed: ['rate<0.02'], http_req_duration: ['p(95)<1500'] } },
  load: { vus: 10, duration: '2m', thresholds: { http_req_failed: ['rate<0.05'], http_req_duration: ['p(95)<2000'] } },
  stress: { stages: [{ duration: '30s', target: 10 }, { duration: '1m', target: 30 }, { duration: '30s', target: 0 }], thresholds: { http_req_failed: ['rate<0.1'] } },
};
