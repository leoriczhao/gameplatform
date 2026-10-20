import { useEffect, useMemo, useRef, useState } from "react";

/* L3 沙箱渲染器宿主（设计 16 §5.2/§5.4）。
   - iframe 响应头带 CSP sandbox（opaque origin），读不到宿主 DOM/Cookie/Storage；
   - 帧内 Worker + OffscreenCanvas 自绘，宿主只做协议转发与看门狗；
   - 任何 error/超时 → onFallback()，由 UgBoard 切回声明式渲染并记住本次会话。 */
export default function SandboxBoard({
  state, meta, onCellClick = null, cellSize = 36, instant = false,
  onSfx = null, onFallback = null,
}) {
  const board = meta?.board || {};
  const w = Math.max(1, Number(board.width) || 1);
  const h = Math.max(1, Number(board.height) || 1);
  const slug = meta?.slug;
  const version = meta?.version;

  const wrapRef = useRef(null);
  const frameRef = useRef(null);
  const readyRef = useRef(false);
  const stateRef = useRef(state);
  const lastSentRef = useRef(null);
  const rafRef = useRef(0);
  const sizeRef = useRef({ w: 0, h: 0, dpr: 0 });
  const [failed, setFailed] = useState(false);

  const src = useMemo(
    () => (slug && version
      ? "/api/ugc/render/" + encodeURIComponent(slug) + "/" +
        encodeURIComponent(version) + "/frame"
      : null),
    [slug, version],
  );

  stateRef.current = state;

  /* ------------------------------------------------------------ 布局尺寸 */
  const post = (msg) => {
    const win = frameRef.current?.contentWindow;
    if (win && readyRef.current) win.postMessage(msg, "*");
  };

  useEffect(() => {
    if (!src) return undefined;
    const el = wrapRef.current;
    if (!el) return undefined;
    const fit = () => {
      const avail = el.clientWidth || (w * cellSize);
      const scale = Math.min(1, avail / Math.max(1, w * cellSize));
      const cw = Math.max(1, Math.round(w * cellSize * scale));
      const ch = Math.max(1, Math.round(h * cellSize * scale));
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const prev = sizeRef.current;
      if (prev.w === cw && prev.h === ch && prev.dpr === dpr) return;
      sizeRef.current = { w: cw, h: ch, dpr };
      const frame = frameRef.current;
      if (frame) {
        frame.style.width = cw + "px";
        frame.style.height = ch + "px";
      }
      post({ type: "resize", width: cw, height: ch, dpr });
    };
    fit();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(fit) : null;
    if (ro) ro.observe(el);
    window.addEventListener("resize", fit);
    return () => {
      if (ro) ro.disconnect();
      window.removeEventListener("resize", fit);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, w, h, cellSize]);

  /* ------------------------------------------------------- 协议 / 看门狗 */
  useEffect(() => {
    if (!src) return undefined;
    const onMessage = (ev) => {
      const win = frameRef.current?.contentWindow;
      if (!win || ev.source !== win) return;      // 只接受本帧
      const d = ev.data || {};
      if (d.type === "ready") {
        readyRef.current = true;
        lastSentRef.current = null;
        const s = sizeRef.current;
        if (s.w) post({ type: "resize", width: s.w, height: s.h, dpr: s.dpr });
        post({ type: "state", state: stateRef.current });
        if (instant) post({ type: "tick", t: 0, dt: 0 });
        return;
      }
      if (d.type === "cell") {
        if (onCellClick) onCellClick(Number(d.x) | 0, Number(d.y) | 0);
        return;
      }
      if (d.type === "sfx") {
        if (onSfx) onSfx(String(d.name));
        return;
      }
      if (d.type === "error") {
        readyRef.current = false;
        setFailed(true);
        if (onFallback) onFallback(String(d.message || "renderer error"));
        return;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, onCellClick, onSfx, onFallback]);

  /* 状态变化 → state（instant 模式顺带推一帧 tick） */
  useEffect(() => {
    if (failed || !readyRef.current) return;
    if (lastSentRef.current !== state) {
      lastSentRef.current = state;
      post({ type: "state", state });
      if (instant) post({ type: "tick", t: 0, dt: 0 });
    }
  }, [state, failed, instant]);

  useEffect(() => {
    if (failed || !src || instant) return undefined;
    let last = performance.now();
    const loop = (now) => {
      const dt = Math.min(100, now - last);
      last = now;
      post({ type: "tick", t: now, dt });
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [instant, failed, src]);

  /* 卸载 → dispose */
  useEffect(() => () => {
    const win = frameRef.current?.contentWindow;
    if (win && readyRef.current) win.postMessage({ type: "dispose" }, "*");
    readyRef.current = false;
  }, [src]);

  if (failed || !src) return null;

  const style = {
    width: w * cellSize,
    height: h * cellSize,
    maxWidth: "100%",
    border: 0,
    display: "block",
    background: "transparent",
  };
  return (
    <div ref={wrapRef} className="flex w-full justify-center">
      <iframe
        ref={frameRef}
        title={(meta?.title || slug || "game") + " renderer"}
        src={src}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        scrolling="no"
        style={style}
      />
    </div>
  );
}
