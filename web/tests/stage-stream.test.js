import test from "node:test";
import assert from "node:assert/strict";
import { createSseParser, openMatchStream, parseEventBlock } from "../src/stage/matchStream.js";

const encoder = new TextEncoder();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(check, timeoutMs = 2000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (check()) return;
    await sleep(5);
  }
  throw new Error("waitFor timeout");
}

function sseBlock(seq, type, data = {}) {
  return "id: " + seq + "\nevent: " + type + "\ndata: "
    + JSON.stringify({ ...data, type, seq, server_time: 1700000000000 }) + "\n\n";
}

/* 每次 fetch 一道脚本：{status} 直接失败，{run(controller)} 推流。
   abort 时主动 error 流，模拟真实 fetch 在取消后的行为。 */
function scriptedFetch(scripts) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    const index = calls.length;
    calls.push({ url, options });
    const script = scripts[Math.min(index, scripts.length - 1)];
    if (script.status && script.status !== 200) {
      return { ok: false, status: script.status, body: null };
    }
    const body = new ReadableStream({
      start(controller) {
        options.signal?.addEventListener("abort", () => {
          try { controller.error(new DOMException("Aborted", "AbortError")); } catch (err) { /* closed */ }
        });
        script.run?.(controller);
      },
    });
    return { ok: true, status: 200, body };
  };
  return { fetchImpl, calls };
}

function streamWith(blocks, { close = true } = {}) {
  return (controller) => {
    for (const block of blocks) controller.enqueue(encoder.encode(block));
    if (close) controller.close();
  };
}

test("SSE parser handles split chunks, multi-line data, comments and bad frames", () => {
  const parser = createSseParser();
  const block = "id: 4\nevent: tick\ndata: {\"a\":1,\ndata: \"b\":2}\n\n";
  assert.deepEqual(parser.push(block.slice(0, 12)), []);
  const events = parser.push(block.slice(12));
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "tick");
  assert.equal(events[0].seq, 4);
  assert.equal(events[0].a, 1);

  assert.deepEqual(parser.push(": 心跳\n\n"), []);
  assert.deepEqual(parser.push("id: 5\ndata: not-json\n\n"), []);
  assert.deepEqual(parser.push("event: x\n\n"), []);
  assert.equal(parseEventBlock("id: 6\ndata: [1]"), null);
  const crlf = parser.push("id: 7\r\nevent: ping\r\ndata: {\"server_time\":9}\r\n\r\n");
  assert.equal(crlf.length, 1);
  assert.equal(crlf[0].server_time, 9);
});

test("reconnect resumes from Last-Event-ID and stops after a terminal snapshot", async () => {
  const scripts = [
    { run: streamWith([sseBlock(1, "snapshot", { status: "active", seats: [] })]) },
    { run: streamWith([sseBlock(2, "snapshot", { status: "finished", seats: [] })]) },
  ];
  const { fetchImpl, calls } = scriptedFetch(scripts);
  const statuses = [];
  const events = [];
  const handle = openMatchStream({
    uid: "abc123", token: "tok", fetchImpl,
    minRetryMs: 5, maxRetryMs: 10, idleTimeoutMs: 0,
    onEvent: (event) => events.push(event),
    onStatus: (status) => statuses.push(status),
  });
  await waitFor(() => statuses.some((status) => status.state === "ended"));
  assert.equal(events.length, 2);
  assert.equal(events[1].status, "finished");
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /\/api\/v2\/matches\/abc123\/stream\?since=1/);
  assert.equal(calls[1].options.headers["Last-Event-ID"], "1");
  assert.equal(calls[1].options.headers.Authorization, "Bearer tok");
  assert.equal(statuses.filter((status) => status.state === "open").length, 2);
  assert.ok(statuses.some((status) => status.state === "reconnecting" && status.reason === "ended"));
  await sleep(30);
  assert.equal(calls.length, 2);          // 终局快照之后不再重连
  handle.close();
});

test("401/403/404 fail immediately without retrying", async () => {
  const { fetchImpl, calls } = scriptedFetch([{ status: 403 }]);
  const statuses = [];
  const handle = openMatchStream({
    uid: "private", fetchImpl, minRetryMs: 5, idleTimeoutMs: 0,
    onEvent: () => {}, onStatus: (status) => statuses.push(status),
  });
  await waitFor(() => statuses.some((status) => status.state === "failed"));
  await sleep(30);
  assert.equal(calls.length, 1);
  assert.equal(statuses.find((status) => status.state === "failed").status, 403);
  handle.close();
});

test("close() stops a pending reconnect", async () => {
  const { fetchImpl, calls } = scriptedFetch([
    { run: streamWith([sseBlock(1, "snapshot", { status: "active", seats: [] })]) },
  ]);
  const statuses = [];
  const handle = openMatchStream({
    uid: "abc", fetchImpl, minRetryMs: 20, idleTimeoutMs: 0,
    onEvent: () => {}, onStatus: (status) => statuses.push(status),
  });
  await waitFor(() => statuses.some((status) => status.state === "reconnecting"));
  handle.close();
  await sleep(40);
  assert.equal(calls.length, 1);
  assert.equal(statuses[statuses.length - 1].state, "closed");
});

test("a silent stream trips the idle watchdog and reconnects", async () => {
  const scripts = [
    { run: () => {} },
    { run: streamWith([sseBlock(2, "snapshot", { status: "finished", seats: [] })]) },
  ];
  const { fetchImpl, calls } = scriptedFetch(scripts);
  const statuses = [];
  const handle = openMatchStream({
    uid: "idle", fetchImpl, minRetryMs: 5, maxRetryMs: 10, idleTimeoutMs: 10,
    onEvent: () => {}, onStatus: (status) => statuses.push(status),
  });
  await waitFor(() => calls.length === 2);
  assert.ok(statuses.some((status) => status.state === "reconnecting" && status.reason === "idle"));
  handle.close();
});
