/* Official OpenEnv WS frames, one environment per connection.
   There are no response IDs: reject concurrent requests rather than guessing
   which reset/step an observation belongs to. Never reconnect or retry a step. */
export function createOpenEnvClient(game, {
  signal,
  WebSocketImpl = globalThis.WebSocket,
  baseUrl = globalThis.location?.href,
  connectTimeoutMs = 10_000,
  requestTimeoutMs = 60_000,
} = {}) {
  let socket = null;
  let pending = null;
  let timer = null;
  let closedError = null;

  const abortError = () => new DOMException("Aborted", "AbortError");
  const stop = (error) => {
    if (closedError) return;
    closedError = error;
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
    if (socket) {
      socket.removeEventListener("open", onOpen);
      socket.removeEventListener("message", onMessage);
      socket.removeEventListener("error", onError);
      socket.removeEventListener("close", onClose);
      if (socket.readyState < 2) socket.close();
    }
    const request = pending;
    pending = null;
    request?.reject(error);
  };
  const onAbort = () => stop(abortError());
  const onError = () => stop(new Error("OpenEnv WebSocket 连接失败"));
  const onClose = (event) => stop(new Error(
    `OpenEnv WebSocket 已断开 (${event.code})${event.reason ? `: ${event.reason}` : ""}`));

  const send = () => {
    clearTimeout(timer);
    timer = setTimeout(() => stop(new Error("OpenEnv 请求超时；环境已关闭")), requestTimeoutMs);
    try { socket.send(JSON.stringify(pending.message)); }
    catch (error) { stop(error); }
  };
  const onOpen = () => send();
  const onMessage = (event) => {
    let frame;
    try { frame = JSON.parse(event.data); }
    catch { stop(new Error("OpenEnv 返回了无效 JSON")); return; }
    if (frame?.type === "error") {
      const error = new Error(frame.data?.message || "OpenEnv 环境请求失败");
      error.code = frame.data?.code;
      error.details = frame.data;
      stop(error);
      return;
    }
    if (!pending || frame?.type !== pending.expected || !frame.data
        || typeof frame.data !== "object" || Array.isArray(frame.data)) {
      stop(new Error("OpenEnv 返回了非预期响应"));
      return;
    }
    clearTimeout(timer);
    const request = pending;
    pending = null;
    request.resolve(frame.data);
  };

  const request = (message, expected) => {
    if (closedError) return Promise.reject(closedError);
    if (pending) return Promise.reject(new Error("OpenEnv 同一连接不允许并发请求"));
    return new Promise((resolve, reject) => {
      pending = { message, expected, resolve, reject };
      if (socket) {
        if (socket.readyState === 1) send();
        else stop(new Error("OpenEnv WebSocket 已断开"));
        return;
      }
      try {
        const url = new URL(`/api/openenv/${encodeURIComponent(game)}/ws`, baseUrl);
        url.protocol = url.protocol === "https:" || url.protocol === "wss:" ? "wss:" : "ws:";
        socket = new WebSocketImpl(url.href);
        socket.addEventListener("open", onOpen);
        socket.addEventListener("message", onMessage);
        socket.addEventListener("error", onError);
        socket.addEventListener("close", onClose);
        timer = setTimeout(() => stop(new Error("OpenEnv WebSocket 连接超时")), connectTimeoutMs);
      } catch (error) { stop(error); }
    });
  };

  if (signal?.aborted) onAbort();
  else signal?.addEventListener("abort", onAbort, { once: true });

  return {
    // reset/step return StepResult-shaped data; .observation is the observation dict.
    reset: (data = {}) => request({ type: "reset", data }, "observation"),
    step: (action) => request({ type: "step", data: { value: action } }, "observation"),
    state: () => request({ type: "state" }, "state"),
    close: () => stop(new Error("OpenEnv 环境已关闭")),
  };
}
