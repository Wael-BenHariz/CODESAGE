import http from 'k6/http';
import { check } from 'k6';
import { optionsByScenario } from './lib/options.js';
export const options = optionsByScenario.load;
export default function () { const r = request(); check(r, { 'endpoint responds': x => x.status === 200 }); }
function request() { return __ENV.K6_ACCESS_TOKEN ? http.get(`${__ENV.BASE_URL}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${__ENV.K6_ACCESS_TOKEN}` } }) : http.get(`${__ENV.BASE_URL}/api/v1/health`); }
