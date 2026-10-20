import test from "node:test";
import assert from "node:assert/strict";
import { getEventListeners } from "node:events";
import { rebuildReplay } from "../src/replay.js";
import { createOpenEnvClient } from "../src/openenv.js";
import { mockWebSockets } from "./helpers/mock-websocket.js";

const record = {
  schema_version: 1, game: "counter", game_version: "1.0.0", seed: 0,
  options: { start: 7 }, moves: [{ action: 2, opponent: 3 }, { action: 2, opponent: 0 }],
};

// Two packages have different dynamics and rendering metadata. The currently
// published version can change, but each WS episode keeps its reset version.
function server({ stateVersion, failOn, missingStateOn, onRequest } = {}) {
  let published = "2.0.0";
  const transport = mockWebSockets((message, socket) => {
    if (onRequest?.(message, socket)) return;
    if (message.type === failOn) {
      socket.message({ type: "error", data: { message: "environment failed", code: "EXECUTION_ERROR" } });
      return;
    }
    const meta = () => ({ board: { style: socket.version === "1.0.0" ? "old" : "new" } });
    if (message.type === "state") {
      socket.message({ type: "state", data: { episode_id: "episode", step_count: socket.tick,
        game_state: { n: socket.n, tick: socket.tick },
        environment: { game: "counter", version: stateVersion || socket.version || published, meta: meta() } } });
      return;
    }
    if (message.type === "reset") {
      socket.version = message.data.version || published;
      socket.n = message.data.options?.start || 0;
      socket.tick = 0;
    } else if (message.type === "step") {
      const action = message.data.value;
      const value = typeof action === "object" ? action.p0 + action.p1 : action;
      socket.n += value * (socket.version === "1.0.0" ? 1 : 100);
      socket.tick++;
    } else {
      assert.fail("unexpected message type " + message.type);
    }
    socket.message({ type: "observation", data: {
      observation: { type: "tensor", data: [[socket.n]], shape: [1, 1], dtype: "float32",
        state: message.type === missingStateOn ? null : { n: socket.n, tick: socket.tick }, metadata: {} },
      reward: 0, done: false,
    } });
  });
  return {
    ...transport,
    publish: (version) => { published = version; },
    createClient: (game, { signal }) => createOpenEnvClient(game, {
      WebSocketImpl: transport.WebSocketImpl, baseUrl: "http://example.test", signal,
    }),
  };
}
function closed(socket) {
  assert.equal(socket.closeCalls, 1);
  assert.equal(socket.listenerCount, 0);
}

test("old PvE replay preserves zero seed/options/opponent moves and version-specific rendering", async () => {
  const backend = server();
  const progress = [];
  const result = rebuildReplay(record, {
    createClient: backend.createClient,
    onProgress: (states, meta) => { progress.push({ states, meta }); backend.publish("3.0.0"); },
  });
  backend.sockets[0].open();
  assert.deepEqual(await result, [{ n: 7, tick: 0 }, { n: 12, tick: 1 }, { n: 14, tick: 2 }]);
  assert.equal(backend.sockets.length, 1);
  const socket = backend.sockets[0];
  assert.equal(socket.url, "ws://example.test/api/openenv/counter/ws");
  assert.deepEqual(socket.sent, [
    { type: "reset", data: { seed: 0, version: "1.0.0", options: { start: 7 }, include_state: true } },
    { type: "state" },
    { type: "step", data: { value: { p0: 2, p1: 3 } } },
    { type: "step", data: { value: { p0: 2, p1: 0 } } },
  ]);
  assert.deepEqual(progress.map((p) => p.states.length), [1, 3]);
  assert.ok(progress.every((p) => p.meta.board.style === "old"));
  closed(socket);
});

test("another recorded version uses its own dynamics and omits absent options", async () => {
  const backend = server();
  const result = rebuildReplay({ ...record, game_version: "2.0.0", options: null, moves: [{ action: 2 }] }, {
    createClient: backend.createClient,
    onProgress: (_, meta) => assert.equal(meta.board.style, "new"),
  });
  backend.sockets[0].open();
  assert.deepEqual(await result, [{ n: 0, tick: 0 }, { n: 200, tick: 1 }]);
  assert.deepEqual(backend.sockets[0].sent[0].data, { seed: 0, version: "2.0.0", include_state: true });
  closed(backend.sockets[0]);
});

test("missing and mismatched versions never silently replay latest", async () => {
  await assert.rejects(rebuildReplay({ schema_version: 1, seed: 0 }, {
    createClient: () => assert.fail("must not open without a version"),
  }), /版本/);
  const backend = server({ stateVersion: "2.0.0" });
  const result = rebuildReplay(record, { createClient: backend.createClient,
    onProgress: () => assert.fail("must not render a different version"),
  });
  backend.sockets[0].open();
  await assert.rejects(result, /不一致/);
  assert.deepEqual(backend.sockets[0].sent.map((m) => m.type), ["reset", "state"]);
  closed(backend.sockets[0]);
});

for (const operation of ["reset", "state", "step"]) {
  test(operation + " errors close the replay without retrying an action", async () => {
    const backend = server({ failOn: operation });
    const result = rebuildReplay(record, { createClient: backend.createClient });
    backend.sockets[0].open();
    await assert.rejects(result, { message: "environment failed", code: "EXECUTION_ERROR" });
    assert.equal(backend.sockets.length, 1);
    assert.equal(backend.sockets[0].sent.filter((m) => m.type === operation).length, 1);
    closed(backend.sockets[0]);
  });
}

for (const operation of ["reset", "step"]) {
  test("missing full state on " + operation + " is an explicit failure", async () => {
    const backend = server({ missingStateOn: operation });
    const result = rebuildReplay(record, { createClient: backend.createClient });
    backend.sockets[0].open();
    await assert.rejects(result, /完整回放局面/);
    closed(backend.sockets[0]);
  });
}

test("pre-cancelled replay never opens a socket", async () => {
  const controller = new AbortController(); controller.abort();
  const backend = server();
  await assert.rejects(rebuildReplay(record, { createClient: backend.createClient, signal: controller.signal }),
    { name: "AbortError" });
  assert.equal(backend.sockets.length, 0);
});

test("cancelling during connection setup closes without sending reset", async () => {
  const controller = new AbortController(); const backend = server();
  const result = rebuildReplay(record, { createClient: backend.createClient, signal: controller.signal });
  controller.abort();
  await assert.rejects(result, { name: "AbortError" });
  assert.deepEqual(backend.sockets[0].sent, []);
  closed(backend.sockets[0]);
});

for (const operation of ["reset", "state", "step"]) {
  test("cancelling an in-flight " + operation + " ignores late frames and stops progress", async () => {
    const controller = new AbortController();
    let started;
    const reachedOperation = new Promise((resolve) => { started = resolve; });
    const backend = server({ onRequest: (message) => {
      if (message.type === operation) { started(); return true; }
      return false;
    } });
    const progress = [];
    const result = rebuildReplay(record, { createClient: backend.createClient, signal: controller.signal,
      onProgress: (states) => progress.push(states.length),
    });
    const socket = backend.sockets[0]; socket.open();
    await reachedOperation;
    controller.abort();
    await assert.rejects(result, { name: "AbortError" });
    socket.message({ type: "observation", data: { observation: { state: { n: 99 } } } });
    assert.deepEqual(progress, operation === "step" ? [1] : []);
    assert.equal(socket.sent.filter((m) => m.type === operation).length, 1);
    assert.equal(backend.sockets.length, 1);
    assert.equal(getEventListeners(controller.signal, "abort").length, 0);
    closed(socket);
  });
}

for (const atFrame of [1, 16]) {
  test("cancelling from progress at frame " + atFrame + " sends no further steps", async () => {
    const controller = new AbortController(); const backend = server();
    const result = rebuildReplay({ ...record, moves: Array.from({ length: 20 }, () => ({ action: 1 })) }, {
      createClient: backend.createClient, signal: controller.signal,
      onProgress: (states) => { if (states.length === atFrame) controller.abort(); },
    });
    backend.sockets[0].open();
    await assert.rejects(result, { name: "AbortError" });
    assert.equal(backend.sockets[0].sent.filter((m) => m.type === "step").length, atFrame - 1);
    closed(backend.sockets[0]);
  });
}

test("progress handler errors also close the environment", async () => {
  const backend = server();
  const result = rebuildReplay(record, { createClient: backend.createClient,
    onProgress: () => { throw new Error("render failed"); },
  });
  backend.sockets[0].open();
  await assert.rejects(result, /render failed/);
  closed(backend.sockets[0]);
});

test("oversized replay is rejected before opening an environment", async () => {
  const backend = server();
  await assert.rejects(rebuildReplay({ ...record, moves: Array(2000).fill({ action: 1 }) }, {
    createClient: backend.createClient,
  }), /2000/);
  assert.equal(backend.sockets.length, 0);
});
