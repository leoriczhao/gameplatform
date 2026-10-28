/* 对局事件流客户端（docs/design/17 §5.2、§7.6）。

   为什么用 fetch 读 SSE 而不是 EventSource：
   - 需要带 Authorization 头（EventSource 不能自定义请求头）；
   - Last-Event-ID 断线续传的语义正好由我们自己的重连控制。

   职责只有三件事：解析 SSE、断线重连、暴露连接状态。状态更新交给
   reduceMatch（纯函数），这里的 onEvent 直接喂给它。

   重连策略：指数退避 500ms → 8s；收到 401/403/404 直接失败不重试
   （鉴权/不存在重试也没用）；ping 看门狗 40s（服务端 15s 一次 ping），
   静默超时后主动断开重连。 */

import { TERMINAL_STATUS } from "./reduceMatch.js";

const FATAL_STATUS = new Set([401, 403, 404]);

/* 增量 SSE 解析器：`push(text)` 返回已经完整的事件块。
   事件块以空行分隔；`id:` / `event:` / `data:` 三种字段，data 可以多行。 */
export function createSseParser() {
  let buffer = "";
  return {
    push(chunk) {
      buffer += String(chunk ?? "").replace(/\r\n/g, "\n");
      const events = [];
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseEventBlock(block);
        if (event) events.push(event);
        boundary = buffer.indexOf("\n\n");
      }
      return events;
    },
  };
}

export function parseEventBlock(block) {
  const dataLines = [];
  let id = null;
  let type = "message";
  for (const line of String(block ?? "").split("\n")) {
    if (!line || line.startsWith(":")) continue;      // 注释行（心跳）
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") type = value;
    else if (field === "data") dataLines.push(value);
  }
  if (dataLines.length === 0) return null;
  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch (err) {
    return null;                                     // 坏帧直接丢弃，不能中断整条流
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const seq = Number(id ?? data.seq);
  return {
    ...data,
    type: data.type || type,
    seq: Number.isFinite(seq) ? seq : undefined,
  };
}

function streamUrl(uid, lastEventId, baseUrl) {
  const path = `/api/v2/matches/${encodeURIComponent(uid)}/stream`;
  const query = lastEventId ? `?since=${encodeURIComponent(lastEventId)}` : "";
  return `${baseUrl || ""}${path}${query}`;
}

export function openMatchStream({
  uid,
  token = "",
  fetchImpl = globalThis.fetch,
  signal,
  onEvent,
  onStatus = () => {},
  baseUrl = "",
  minRetryMs = 500,
  maxRetryMs = 8000,
  idleTimeoutMs = 40000,
}) {
  let closed = false;
  let attempt = 0;
  let lastEventId = 0;
  let controller = null;
  let reconnectTimer = null;
  let idleTimer = null;
  let idleFired = false;
  let endedAfterSnapshot = false;

  const clearIdle = () => {
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  };

  const stop = (reason) => {
    if (closed) return;
    closed = true;
    clearIdle();
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try { controller?.abort(); } catch (err) { /* already gone */ }
    onStatus({ state: "closed", reason, lastEventId });
  };

  const onAbort = () => stop("aborted");
  if (signal?.aborted) {
    onStatus({ state: "closed", reason: "aborted", lastEventId });
    return { close: () => {}, getLastEventId: () => 0 };
  }
  signal?.addEventListener("abort", onAbort, { once: true });

  const armIdle = () => {
    clearIdle();
    if (closed || idleTimeoutMs <= 0) return;
    idleTimer = setTimeout(() => {
      idleTimer = null;
      if (closed) return;
      idleFired = true;                              // 读循环 catch 里统一发起重连
      try { controller?.abort(); } catch (err) { /* already gone */ }
    }, idleTimeoutMs);
  };

  const scheduleReconnect = (reason) => {
    if (closed) return;
    attempt += 1;
    const delay = Math.min(maxRetryMs, minRetryMs * 2 ** (attempt - 1));
    onStatus({ state: "reconnecting", reason, attempt, delayMs: delay, lastEventId });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const dispatch = (event) => {
    if (closed) return;
    if (Number.isFinite(event.seq) && event.seq > lastEventId) lastEventId = event.seq;
    if (event.type === "snapshot" && TERMINAL_STATUS.includes(event.status)) {
      endedAfterSnapshot = true;                    // 已结束的对局只会回一条 snapshot 然后关流
    }
    onEvent(event);
  };

  const connect = async () => {
    if (closed) return;
    const headers = { Accept: "text/event-stream" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (lastEventId) headers["Last-Event-ID"] = String(lastEventId);
    if (!attempt) onStatus({ state: "connecting", attempt, lastEventId });

    controller = new AbortController();
    let resp;
    try {
      resp = await fetchImpl(streamUrl(uid, lastEventId, baseUrl), {
        headers,
        signal: controller.signal,
      });
    } catch (err) {
      if (!closed) scheduleReconnect("network");
      return;
    }
    if (closed) return;
    if (!resp.ok) {
      if (FATAL_STATUS.has(resp.status)) {
        closed = true;
        clearIdle();
        onStatus({ state: "failed", status: resp.status, lastEventId });
        return;
      }
      scheduleReconnect("http");
      return;
    }

    attempt = 0;
    idleFired = false;
    onStatus({ state: "open", lastEventId });
    armIdle();
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    const parser = createSseParser();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        armIdle();
        for (const event of parser.push(decoder.decode(value, { stream: true }))) {
          dispatch(event);
        }
      }
    } catch (err) {
      if (closed) return;
      if (idleFired) {
        idleFired = false;
        scheduleReconnect("idle");
        return;
      }
      scheduleReconnect("read");
      return;
    }
    if (closed) return;
    if (endedAfterSnapshot) {
      closed = true;
      clearIdle();
      onStatus({ state: "ended", lastEventId });
      return;
    }
    scheduleReconnect("ended");
  };

  connect();

  return {
    close: () => {
      signal?.removeEventListener("abort", onAbort);
      stop("closed");
    },
    getLastEventId: () => lastEventId,
  };
}
