/* 回看帧缓冲 + 播放头（docs/design/17 §7.3 Timeline、§7.6）。

   直播时 View 里只有最新一帧；用户拖动时间线或查看已结束的对局时，按
   需要从 `/frames` 分页拉取。播放头只改 review 状态，渲染由 Stage 决定：
   review.active 时显示 frameFor(review.tick)，否则显示 view.frame。 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getJson } from "../api.js";
import {
  bufferedRanges, createFrameBuffer, frameAt, hasMore, loadedThrough, mergeFramePage,
} from "./frameBuffer.js";

const PAGE_SIZE = 500;
const STEP_MS = 600;          // 回放基础节奏，speed 倍速后为 STEP_MS / speed
const MAX_PAGES_PER_READ = 10;

const IDLE_REVIEW = { active: false, tick: 0, playing: false, speed: 1 };

export function useFrames(uid, { token = "", total = 0, enabled = false } = {}) {
  const bufferRef = useRef(createFrameBuffer());
  const [buffer, setBuffer] = useState(bufferRef.current);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [review, setReview] = useState(IDLE_REVIEW);
  const loadingRef = useRef(false);

  const maxTick = Math.max(0, (total || 0) - 1);

  useEffect(() => {
    bufferRef.current = createFrameBuffer();
    setBuffer(bufferRef.current);
    setReview(IDLE_REVIEW);
    setError(null);
  }, [uid]);

  const loadPage = useCallback(async () => {
    if (!uid || loadingRef.current) return bufferRef.current;
    const current = bufferRef.current;
    if (!hasMore(current)) return current;
    loadingRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const from = current.next ?? 0;
      const page = await getJson(
        `/api/v2/matches/${uid}/frames?from=${from}&limit=${PAGE_SIZE}`,
        token,
      );
      const merged = mergeFramePage(bufferRef.current, page);
      bufferRef.current = merged;
      setBuffer(merged);
      return merged;
    } catch (err) {
      setError(err);
      return bufferRef.current;
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, [uid, token]);

  /* 拉取到 target tick 为止；最多连拉 10 页，避免拖动时卡住主线程。 */
  const ensureFrames = useCallback(async (target) => {
    let current = bufferRef.current;
    for (let i = 0; i < MAX_PAGES_PER_READ; i += 1) {
      if (loadedThrough(current) >= target || !hasMore(current)) break;
      current = await loadPage();
    }
    return current;
  }, [loadPage]);

  useEffect(() => {
    if (!enabled) return undefined;
    loadPage();
    return undefined;
  }, [enabled, loadPage]);

  const openAt = useCallback((tick) => {
    const clamped = Math.max(0, Math.min(maxTick, Math.round(tick)));
    setReview({ active: true, tick: clamped, playing: false, speed: 1 });
    ensureFrames(clamped);
  }, [ensureFrames, maxTick]);

  const backToLive = useCallback(() => setReview(IDLE_REVIEW), []);

  const seek = useCallback((tick) => {
    const clamped = Math.max(0, Math.min(maxTick, Math.round(tick)));
    setReview((prev) => ({ ...prev, active: true, playing: false, tick: clamped }));
    ensureFrames(clamped);
  }, [ensureFrames, maxTick]);

  const step = useCallback((delta) => {
    setReview((prev) => {
      const next = Math.max(0, Math.min(maxTick, prev.tick + delta));
      ensureFrames(next);
      return { ...prev, active: true, playing: false, tick: next };
    });
  }, [ensureFrames, maxTick]);

  const play = useCallback(() => {
    setReview((prev) => {
      const tick = prev.tick >= maxTick ? 0 : prev.tick;
      ensureFrames(Math.min(maxTick, tick + PAGE_SIZE));
      return { ...prev, active: true, playing: true, tick };
    });
  }, [ensureFrames, maxTick]);

  const pause = useCallback(() => setReview((prev) => ({ ...prev, playing: false })), []);

  const setSpeed = useCallback((speed) => {
    const value = Math.max(0.5, Math.min(4, Number(speed) || 1));
    setReview((prev) => ({ ...prev, speed: value }));
  }, []);

  /* 播放节拍：按速度推进，到末尾自动暂停。 */
  useEffect(() => {
    if (!review.playing) return undefined;
    const id = setInterval(() => {
      setReview((prev) => {
        if (!prev.playing) return prev;
        if (prev.tick >= maxTick) return { ...prev, playing: false, tick: maxTick };
        return { ...prev, tick: prev.tick + 1 };
      });
    }, STEP_MS / review.speed);
    return () => clearInterval(id);
  }, [review.playing, review.speed, maxTick]);

  /* 播放时提前缓冲下一页，滑轨不会卡在已加载边界。 */
  useEffect(() => {
    if (!review.active) return;
    if (loadedThrough(bufferRef.current) - review.tick < PAGE_SIZE / 2) ensureFrames(review.tick + PAGE_SIZE);
  }, [review.active, review.tick, ensureFrames]);

  const frameFor = useCallback((tick) => frameAt(bufferRef.current, tick), []);

  return {
    buffer,
    frames: buffer.frames,
    total: buffer.total,
    buffered: bufferedRanges(buffer),
    loading,
    error,
    review,
    maxTick,
    ensureFrames,
    frameFor,
    openAt,
    backToLive,
    seek,
    step,
    play,
    pause,
    setSpeed,
  };
}
