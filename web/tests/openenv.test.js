import test from "node:test";
import assert from "node:assert/strict";
import { getEventListeners } from "node:events";
import { createOpenEnvClient } from "../src/openenv.js";
import { mockWebSockets } from "./helpers/mock-websocket.js";

function fixture(options = {}) {
  const transport = mockWebSockets();
  const controller = new AbortController();
  const env = createOpenEnvClient("game/one", {
    ...transport, signal: controller.signal, baseUrl: "https://example.test/games/game?x=1", ...options,
  });
  return { ...transport, env, controller };
}
const observation = (state = { tick: 0 }) => ({
  type: "observation",
  data: { observation: { type: "tensor", data: [[1]], shape: [1, 1], dtype: "float32",
    state, metadata: {} }, reward: 0, done: false },
});
function cleaned(socket, controller) {
  assert.equal(socket.listenerCount, 0);
  assert.equal(getEventListeners(controller.signal, "abort").length, 0);
}

test("official state/reset/step frames share one socket and return unwrapped data", async () => {
  const { env, sockets, controller } = fixture();
  assert.equal(sockets.length, 0, "connect lazily");
  const beforeReset = env.state();
  const socket = sockets[0];
  assert.equal(socket.url, "wss://example.test/api/openenv/game%2Fone/ws");
  assert.deepEqual(socket.sent, []);
  socket.open();
  assert.deepEqual(socket.sent, [{ type: "state" }]);
  const environment = { game: "game/one", version: "2.0.0", meta: { title: "game" }, max_concurrent_envs: 64 };
  const snapshot = { episode_id: null, step_count: 0, game_state: null, environment };
  socket.message({ type: "state", data: snapshot });
  assert.deepEqual(await beforeReset, snapshot);

  const parameters = { seed: 0, version: "1.0.0", options: { start: 7 }, obs_mode: "board",
    rewards: { win: 5 }, include_state: true };
  const resetting = env.reset(parameters);
  assert.deepEqual(socket.sent.at(-1), { type: "reset", data: parameters });
  const initial = observation();
  initial.data.observation.metadata.environment = { ...environment, version: "1.0.0" };
  socket.message(initial);
  assert.deepEqual(await resetting, initial.data);

  for (const action of [0, [1, 2], { p0: 1, p1: 0 }]) {
    const stepping = env.step(action);
    assert.deepEqual(socket.sent.at(-1), { type: "step", data: { value: action } });
    const next = observation({ tick: 1 });
    next.data.reward = 3;
    next.data.done = true;
    socket.message(next);
    assert.deepEqual(await stepping, next.data);
  }
  const resettingDefault = env.reset();
  assert.deepEqual(socket.sent.at(-1), { type: "reset", data: {} });
  socket.message({ type: "observation", data: { observation: { type: "state", state: { tick: 0 } }, reward: null, done: false } });
  assert.equal((await resettingDefault).observation.type, "state");
  assert.equal(sockets.length, 1);
  env.close(); env.close();
  assert.equal(socket.closeCalls, 1);
  cleaned(socket, controller);
});

test("plain HTTP origin uses ws, and concurrent requests cannot consume each other's responses", async () => {
  const { env, sockets, controller } = fixture({ baseUrl: "http://localhost:8080" });
  const resetting = env.reset({ seed: 42 });
  const socket = sockets[0];
  assert.equal(socket.url, "ws://localhost:8080/api/openenv/game%2Fone/ws");
  await assert.rejects(env.state(), /并发/);
  assert.equal(sockets.length, 1);
  socket.open();
  await assert.rejects(env.step(0), /并发/);
  assert.equal(socket.sent.length, 1);
  socket.message(observation());
  await resetting;
  const state = env.state();
  socket.message({ type: "state", data: { game_state: { tick: 0 } } });
  assert.deepEqual(await state, { game_state: { tick: 0 } });
  env.close();
  cleaned(socket, controller);
});

test("official error frames reject the in-flight request with code/details and fail closed", async () => {
  const { env, sockets, controller } = fixture();
  const result = env.reset();
  const socket = sockets[0];
  socket.open();
  const details = { message: "capacity reached", code: "CAPACITY_REACHED", max_sessions: 64 };
  socket.message({ type: "error", data: details });
  const expected = { message: details.message, code: details.code, details };
  await assert.rejects(result, expected);
  await assert.rejects(env.reset(), expected);
  assert.equal(sockets.length, 1);
  assert.equal(socket.closeCalls, 1);
  cleaned(socket, controller);
});

test("an idle-session error is retained instead of being assigned to a later request", async () => {
  const { env, sockets, controller } = fixture();
  const state = env.state();
  const socket = sockets[0]; socket.open();
  socket.message({ type: "state", data: { game_state: null } });
  await state;
  socket.message({ type: "error", data: { message: "session expired", code: "SESSION_ERROR" } });
  await assert.rejects(env.step(1), { message: "session expired", code: "SESSION_ERROR" });
  assert.equal(socket.sent.length, 1);
  cleaned(socket, controller);
});

test("connection timeout destroys the pending socket and cannot reconnect", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { env, sockets, controller } = fixture({ connectTimeoutMs: 10 });
  const result = env.state();
  t.mock.timers.tick(10);
  await assert.rejects(result, /连接超时/);
  await assert.rejects(env.reset(), /连接超时/);
  assert.equal(sockets.length, 1);
  assert.equal(sockets[0].closeCalls, 1);
  assert.deepEqual(sockets[0].sent, []);
  cleaned(sockets[0], controller);
});

test("a sent step timing out is never retried and late frames are ignored", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { env, sockets, controller } = fixture({ requestTimeoutMs: 20 });
  const reset = env.reset(); const socket = sockets[0]; socket.open();
  socket.message(observation()); await reset;
  const step = env.step(1);
  t.mock.timers.tick(20);
  await assert.rejects(step, /请求超时/);
  socket.message(observation({ tick: 1 }));
  await assert.rejects(env.step(1), /请求超时/);
  assert.equal(socket.sent.filter((m) => m.type === "step").length, 1);
  assert.equal(sockets.length, 1);
  cleaned(socket, controller);
});

test("abort before use opens no connection", async () => {
  const controller = new AbortController(); controller.abort();
  const { env, sockets } = fixture({ signal: controller.signal });
  await assert.rejects(env.reset(), { name: "AbortError" });
  assert.equal(sockets.length, 0);
  assert.equal(getEventListeners(controller.signal, "abort").length, 0);
});

for (const phase of ["connecting", "reset", "step", "idle"]) {
  test("abort cleans up the " + phase + " connection", async () => {
    const { env, sockets, controller } = fixture();
    let pending = env.reset(); const socket = sockets[0];
    if (phase !== "connecting") socket.open();
    if (phase === "step" || phase === "idle") {
      socket.message(observation()); await pending;
      pending = phase === "step" ? env.step(1) : null;
    }
    controller.abort();
    if (pending) await assert.rejects(pending, { name: "AbortError" });
    await assert.rejects(env.state(), { name: "AbortError" });
    socket.message(observation());
    assert.equal(socket.closeCalls, 1);
    assert.equal(sockets.length, 1);
    cleaned(socket, controller);
  });
}

for (const event of ["error", "close"]) {
  test("transport " + event + " rejects a sent step without replaying it", async () => {
    const { env, sockets, controller } = fixture();
    const reset = env.reset(); const socket = sockets[0]; socket.open();
    socket.message(observation()); await reset;
    const step = env.step(1);
    if (event === "close") socket.disconnect(1006, "connection lost");
    else socket.emit("error");
    await assert.rejects(step, /WebSocket/);
    await assert.rejects(env.step(1), /WebSocket/);
    assert.equal(socket.sent.length, 2);
    assert.equal(sockets.length, 1);
    cleaned(socket, controller);
  });
}

for (const frame of ["bad JSON", JSON.stringify({ type: "state", data: {} }),
  JSON.stringify({ type: "observation" }), JSON.stringify({ type: "observation", data: [] })]) {
  test("invalid response fails closed: " + frame, async () => {
    const { env, sockets, controller } = fixture();
    const result = env.reset(); const socket = sockets[0]; socket.open();
    socket.emit("message", { data: frame });
    await assert.rejects(result, /无效 JSON|非预期响应/);
    assert.equal(socket.closeCalls, 1);
    cleaned(socket, controller);
  });
}

test("explicit close rejects pending work and is idempotent", async () => {
  const { env, sockets, controller } = fixture();
  const result = env.reset();
  env.close(); env.close();
  await assert.rejects(result, /已关闭/);
  await assert.rejects(env.step(0), /已关闭/);
  assert.equal(sockets[0].closeCalls, 1);
  cleaned(sockets[0], controller);
});

test("constructor and serialization failures reject and release abort listeners", async () => {
  const failing = fixture({ WebSocketImpl: class { constructor() { throw new Error("constructor failed"); } } });
  await assert.rejects(failing.env.state(), /constructor failed/);
  assert.equal(getEventListeners(failing.controller.signal, "abort").length, 0);
  const { env, sockets, controller } = fixture();
  const cyclic = {}; cyclic.self = cyclic;
  const result = env.step(cyclic); sockets[0].open();
  await assert.rejects(result, /circular/i);
  assert.equal(sockets[0].sent.length, 0);
  cleaned(sockets[0], controller);
});
