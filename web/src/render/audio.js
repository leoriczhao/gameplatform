/* 渲染 v2 · WebAudio 音效播放（docs/design/16 §4.2）。
   约束：默认静音、首次用户手势解锁、并发上限、音量 ≤1、解码/播放失败静默忽略。
   模块顶层不触碰 window/AudioContext，可安全在 node --test 下 import。 */

import { clamp01 } from "./paths.js";

export const MAX_CONCURRENT = 4;
export const MAX_BUFFERS = 24;

function nowSeconds(ctx) {
  return ctx && typeof ctx.currentTime === "number" ? ctx.currentTime : 0;
}

export class AudioEngine {
  constructor(options = {}) {
    this.ctx = null;
    this.master = null;
    this.muted = true;                       // 默认静音（须用户手势解锁）
    this.unlocked = false;
    this.volume = clamp01(options.volume, 1);
    const max = Number(options.maxConcurrent);
    this.maxConcurrent = Number.isFinite(max) ? Math.max(1, Math.min(8, Math.round(max))) : MAX_CONCURRENT;
    this.buffers = new Map();                // url → AudioBuffer | Promise<AudioBuffer|null>
    this.active = [];                        // { source, endsAt }
  }

  isMuted() {
    return this.muted;
  }

  isUnlocked() {
    return this.unlocked;
  }

  /* 用户手势内调用：创建/恢复 AudioContext。任何环境缺失都返回 false，不抛异常。 */
  unlock() {
    try {
      if (this.unlocked && this.ctx) {
        if (this.ctx.state === "suspended" && typeof this.ctx.resume === "function") {
          this.ctx.resume().catch(() => {});
        }
        return true;
      }
      const g = typeof globalThis !== "undefined" ? globalThis : null;
      const AC = g && (g.AudioContext || g.webkitAudioContext);
      if (!AC) return false;
      const ctx = new AC();
      const master = ctx.createGain();
      master.gain.value = this.muted ? 0 : this.volume;
      master.connect(ctx.destination);
      this.ctx = ctx;
      this.master = master;
      this.unlocked = true;
      if (ctx.state === "suspended" && typeof ctx.resume === "function") {
        ctx.resume().catch(() => {});
      }
      return true;
    } catch (err) {
      this.ctx = null;
      this.master = null;
      this.unlocked = false;
      return false;
    }
  }

  setMuted(muted) {
    this.muted = muted !== false;
    if (!this.muted) this.unlock();          // 由点击处理器调用，此时是用户手势
    try {
      if (this.master) this.master.gain.value = this.muted ? 0 : this.volume;
    } catch (err) { /* ignore */ }
    if (this.muted) this.stopAll();
    return this.muted;
  }

  _prune() {
    const t = nowSeconds(this.ctx);
    this.active = this.active.filter((a) => a && t <= a.endsAt);
    if (this.active.length > this.maxConcurrent) {
      const drop = this.active.splice(0, this.active.length - this.maxConcurrent);
      drop.forEach((a) => { try { a.source.stop(); } catch (err) { /* ignore */ } });
    }
  }

  _buffer(url) {
    if (this.buffers.has(url)) return this.buffers.get(url);
    const ctx = this.ctx;
    const task = (async () => {
      if (typeof fetch !== "function") return null;
      const res = await fetch(url, { cache: "force-cache", credentials: "same-origin" });
      if (!res || !res.ok) return null;
      const data = await res.arrayBuffer();
      return await new Promise((resolve) => {
        let settled = false;
        const done = (buf) => { if (!settled) { settled = true; resolve(buf || null); } };
        try {
          const p = ctx.decodeAudioData(data, done, () => done(null));
          if (p && typeof p.then === "function") p.then(done, () => done(null));
        } catch (err) { done(null); }
      });
    })().catch(() => null);
    this.buffers.set(url, task);
    if (this.buffers.size > MAX_BUFFERS) {
      const first = this.buffers.keys().next();
      if (!first.done) this.buffers.delete(first.value);
    }
    return task;
  }

  /* 播放一次；muted/未解锁/URL 非法/解码失败都静默返回 false。 */
  play(url, volume) {
    try {
      if (this.muted || !this.unlocked || !this.ctx || !this.master || !url) return false;
      this._prune();
      if (this.active.length >= this.maxConcurrent) {
        const oldest = this.active.shift();
        try { oldest.source.stop(); } catch (err) { /* ignore */ }
      }
      this._buffer(url).then((buf) => {
        if (!buf || this.muted || !this.unlocked || !this.ctx) return;
        try {
          const src = this.ctx.createBufferSource();
          src.buffer = buf;
          const gain = this.ctx.createGain();
          gain.gain.value = clamp01(volume, 1) * this.volume;
          src.connect(gain);
          gain.connect(this.master);
          const startAt = nowSeconds(this.ctx);
          this.active.push({ source: src, endsAt: startAt + (buf.duration || 0) + 0.05 });
          src.onended = () => {
            this.active = this.active.filter((a) => a.source !== src);
          };
          src.start();
        } catch (err) { /* ignore */ }
      }).catch(() => {});
      return true;
    } catch (err) {
      return false;
    }
  }

  stopAll() {
    const list = this.active;
    this.active = [];
    list.forEach((a) => { try { a.source.stop(); } catch (err) { /* ignore */ } });
  }

  close() {
    this.stopAll();
    this.buffers.clear();
    try { if (this.ctx && typeof this.ctx.close === "function") this.ctx.close(); } catch (err) { /* ignore */ }
    this.ctx = null;
    this.master = null;
    this.unlocked = false;
  }
}

export function createAudioEngine(options) {
  return new AudioEngine(options);
}
