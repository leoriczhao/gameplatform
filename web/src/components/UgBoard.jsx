/* 通用棋盘门面（11 P4 / 16 §6）：保持既有 props
   {state, meta, onCellClick, cellSize}，四个调用点零改动；新增 instant / interactive。
   职责：归一化 meta → 选渲染器 → 渲染 HUD → 预加载资源 → 音效静音开关。
   渲染器选择：
     meta.renderer_enabled 且未降级 → SandboxBoard（L3：opaque-origin iframe + Worker）
     board.renderer=dom / prefers-reduced-motion / canvas 不可用 / 极简棋盘 → BoardDom
     其余 → BoardCanvas
   外层容器沿用 v1 的白底卡片（不额外包 .board-shell；Watch/WatchReplay 调用点已有包裹）。 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Volume2Icon, VolumeXIcon } from "lucide-react";
import BoardCanvas from "../render/BoardCanvas.jsx";
import BoardDom from "../render/BoardDom.jsx";
import Hud from "../render/Hud.jsx";
import SandboxBoard from "../render/SandboxBoard.jsx";
import { assetContext, collectEvents, normalizeMeta } from "../render/schema.js";
import { assetUrl, createAssetCache } from "../render/assets.js";
import { createAudioEngine } from "../render/audio.js";

const SIMPLE_MAX_CELLS = 64;      // 「极简棋盘」阈值：≤64 格且无新特性 → DOM（无障碍优先）

function canvasAvailable() {
  try {
    if (typeof document === "undefined") return false;
    const c = document.createElement("canvas");
    if (!c || typeof c.getContext !== "function") return false;
    return !!c.getContext("2d");
  } catch (err) {
    return false;
  }
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    let mq;
    try { mq = window.matchMedia("(prefers-reduced-motion: reduce)"); } catch (err) { return undefined; }
    if (!mq) return undefined;
    const apply = () => setReduced(!!mq.matches);
    apply();
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
    if (typeof mq.addListener === "function") {
      mq.addListener(apply);
      return () => mq.removeListener(apply);
    }
    return undefined;
  }, []);
  return reduced;
}

/* 走 DOM 的条件（16 §6「极简棋盘」）：
   1) 旧 v1 包（无任何 v2 声明）—— 直接复刻 v1 的 grid/button 渲染，保证逐像素级兼容，
      也让既有选择器（.grid > button）与无障碍语义保持不变；
   2) v2 包但没有任何 canvas 专属能力（动效/精灵/矢量/图层/事件/单位），且棋盘 ≤64 格。 */
function isSimpleBoard(model) {
  if (!model) return true;
  if (model.legacy) return true;
  if (model.hasLayers || model.hasEvents || model.hasAnims || model.hasEnter) return false;
  if (model.hasSprites || model.hasVectors) return false;
  if (model.background.kind !== "plain") return false;
  if (Object.keys(model.units).length > 0) return false;
  const w = model.width || 1;
  const h = model.height || 1;
  return w * h <= SIMPLE_MAX_CELLS;
}

export default function UgBoard({
  state, meta, onCellClick = null, cellSize = 36, instant = false, interactive = null,
}) {
  const model = useMemo(() => normalizeMeta(meta), [meta]);
  const reducedMotion = usePrefersReducedMotion();
  const [canvasOk] = useState(canvasAvailable);
  const [cache, setCache] = useState(null);
  const [assetsVersion, setAssetsVersion] = useState(0);
  const [muted, setMuted] = useState(true);          // 默认静音（16 §4.2）
  const engineRef = useRef(null);
  const ctxInfo = useMemo(() => assetContext(model), [model]);
  const canInteract = interactive === null ? !!onCellClick : !!interactive;

  /* L3 沙箱渲染器失败记忆（16 §5.4）：同一 slug+version 本会话只尝试一次 */
  const sandboxKey = model.renderer.declared && model.slug
    ? "ugc-renderer-fail:" + model.slug + ":" + (model.version || "")
    : null;
  const [sandboxFailed, setSandboxFailed] = useState(false);

  useEffect(() => {
    if (!sandboxKey || typeof window === "undefined") return;
    try {
      setSandboxFailed(window.sessionStorage.getItem(sandboxKey) === "1");
    } catch (err) { /* 隐私模式下忽略 */ }
  }, [sandboxKey]);

  const handleSandboxFallback = useCallback((message) => {
    setSandboxFailed(true);
    if (sandboxKey && typeof window !== "undefined") {
      try { window.sessionStorage.setItem(sandboxKey, "1"); } catch (err) { /* ignore */ }
    }
    if (message && typeof console !== "undefined" && console.warn) {
      console.warn("[ugc-renderer] 沙箱渲染器失败，已回退声明式渲染：", message);
    }
  }, [sandboxKey]);

  /* ------------------------------------------------------------ 资源预加载 */
  useEffect(() => {
    if (!model.hasSprites) {
      setCache(null);
      return undefined;
    }
    const next = createAssetCache();
    let alive = true;
    next.preload(ctxInfo, model.assets)
      .catch(() => 0)
      .then(() => {
        if (!alive) { next.close(); return; }
        setCache(next);
        setAssetsVersion((v) => v + 1);      // 触发一次重绘（sprite 就绪后替换 glyph）
      });
    return () => {
      alive = false;
      next.close();
    };
  }, [model, ctxInfo]);

  /* ---------------------------------------------------------------- 音效 */
  useEffect(() => {
    const engine = createAudioEngine();
    engineRef.current = engine;
    return () => { engine.close(); engineRef.current = null; };
  }, []);

  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || !model.hasSounds) return;
    const events = collectEvents(state);
    for (let i = 0; i < events.length; i += 1) {
      const decl = model.events[events[i].name];
      if (!decl || !decl.sound) continue;
      const sound = model.sounds[decl.sound];
      if (!sound) continue;
      engine.play(assetUrl(ctxInfo, sound.file), sound.volume);
    }
  }, [state, model, ctxInfo]);

  /* 沙箱渲染器请求音效（帧无音频权限，由宿主播放；16 §5.3） */
  const playSfx = useCallback((name) => {
    const engine = engineRef.current;
    if (!engine || !model.hasSounds) return;
    const sound = model.sounds[name];
    if (!sound) return;
    engine.play(assetUrl(ctxInfo, sound.file), sound.volume);
  }, [model, ctxInfo]);

  const unlockAudio = useCallback(() => {
    const engine = engineRef.current;
    if (engine && model.hasSounds) engine.unlock();
  }, [model.hasSounds]);

  const toggleMute = useCallback(() => {
    const engine = engineRef.current;
    setMuted((prev) => {
      const nextMuted = !prev;
      if (engine) engine.setMuted(nextMuted);
      return nextMuted;
    });
  }, []);

  /* ------------------------------------------------------------- 选渲染器 */
  const wantSandbox = model.renderer.declared && model.renderer.enabled
    && !reducedMotion && canvasOk && !sandboxFailed;
  let renderer = "canvas";
  if (wantSandbox) {
    renderer = "sandbox";                          // 16 §5：L3 沙箱渲染器优先
  } else if (model.boardRenderer === "dom") {
    renderer = "dom";
  } else if (reducedMotion) {
    renderer = "dom";                              // 16 §6：prefers-reduced-motion 回退 DOM
  } else if (model.boardRenderer === "canvas") {
    renderer = canvasOk ? "canvas" : "dom";
  } else if (isSimpleBoard(model)) {
    renderer = "dom";
  } else {
    renderer = canvasOk ? "canvas" : "dom";
  }

  const showFooter = model.hasHud || model.hasSounds;

  return (
    <div
      className="inline-block rounded-lg border border-border bg-white p-1 shadow-sm"
      onPointerDown={unlockAudio}
    >
      {renderer === "sandbox" ? (
        <SandboxBoard
          state={state}
          meta={meta}
          cellSize={model.cell.declared ? model.cell.size : cellSize}
          instant={instant}
          onCellClick={canInteract ? onCellClick : null}
          onSfx={playSfx}
          onFallback={handleSandboxFallback}
        />
      ) : renderer === "dom" ? (
        <BoardDom
          state={state}
          model={model}
          onCellClick={onCellClick}
          cellSize={cellSize}
          interactive={canInteract}
        />
      ) : (
        <BoardCanvas
          state={state}
          model={model}
          onCellClick={onCellClick}
          cellSize={cellSize}
          instant={instant}
          interactive={canInteract}
          assets={cache}
          assetsVersion={assetsVersion}
        />
      )}
      {showFooter && (
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <Hud items={model.hud} state={state} />
          </div>
          {model.hasSounds && (
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? "开启音效" : "静音"}
              title={muted ? "开启音效" : "静音"}
              className="mb-1 inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-white text-muted-foreground transition-colors hover:text-foreground"
            >
              {muted ? <VolumeXIcon className="size-4" /> : <Volume2Icon className="size-4" />}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
