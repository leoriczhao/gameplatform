// Lightweight API smoke load test. Defaults to a local backend.
//   k6 run loadtest/k6-smoke.js
//   BASE_URL=https://staging.example VUS=5 DURATION=30s k6 run loadtest/k6-smoke.js
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = (__ENV.BASE_URL || "http://127.0.0.1:8080").replace(/\/$/, "");
const VUS = Number(__ENV.VUS || 5);
const DURATION = __ENV.DURATION || "20s";

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
    checks: ["rate>0.99"],
  },
  tags: { suite: "api-smoke" },
};

function isReady(response) {
  if (response.status !== 200) return false;
  try {
    return response.json("status") === "ready";
  } catch (error) {
    return false;
  }
}

function hasThreeGames(response) {
  if (response.status !== 200) return false;
  try {
    const games = response.json("games") || [];
    return games.length >= 3;
  } catch (error) {
    return false;
  }
}

export default function () {
  const ready = http.get(BASE + "/api/ready", { tags: { name: "GET /api/ready" } });
  check(ready, {
    "ready 200": (response) => response.status === 200,
    "ready payload": isReady,
  });

  const games = http.get(BASE + "/api/games", { tags: { name: "GET /api/games" } });
  check(games, {
    "games 200": (response) => response.status === 200,
    "games >= 3": hasThreeGames,
  });

  const rooms = http.get(BASE + "/api/v1/microrts/play/rooms", {
    tags: { name: "GET /play/rooms" },
  });
  check(rooms, { "rooms 200": (response) => response.status === 200 });

  sleep(1);
}
