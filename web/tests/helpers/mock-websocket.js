/* Native WebSocket surface only; every instance has independent listeners/state. */
export function mockWebSockets(onSend) {
  const sockets = [];
  class MockWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.closeCalls = 0;
      this.listeners = new Map();
      sockets.push(this);
    }
    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type).add(listener);
    }
    removeEventListener(type, listener) {
      this.listeners.get(type)?.delete(listener);
    }
    emit(type, event = {}) {
      for (const listener of this.listeners.get(type) || []) listener(event);
    }
    open() {
      this.readyState = 1;
      this.emit("open");
    }
    message(frame) {
      this.emit("message", { data: JSON.stringify(frame) });
    }
    send(text) {
      if (this.readyState !== 1) throw new Error("socket is not open");
      const message = JSON.parse(text);
      this.sent.push(message);
      onSend?.(message, this);
    }
    disconnect(code = 1006, reason = "") {
      this.readyState = 3;
      this.emit("close", { code, reason });
    }
    close() {
      this.closeCalls++;
      this.disconnect(1000);
    }
    get listenerCount() {
      return [...this.listeners.values()].reduce((sum, set) => sum + set.size, 0);
    }
  }
  return { sockets, WebSocketImpl: MockWebSocket };
}
