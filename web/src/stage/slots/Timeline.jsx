/* Timeline（docs/design/17 §7.3）：直播细轨 + 回看。点击/拖动轨道即进入回看，
   LIVE 或 Esc 回到直播。帧由 /frames 分页加载，浅色区间表示已缓冲；
   轨道上的小圆点是事件刻度（引擎事件 + 服务端 mark），点击跳到该帧。 */

import { useMemo } from "react";
import { Pause, Play, Radio, SkipBack, SkipForward } from "lucide-react";
import { collectMarks } from "../timelineMarks.js";

const SPEEDS = [0.5, 1, 2, 4];

function pct(value, total) {
  if (!total) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}

export default function Timeline({ view, frames }) {
  const review = frames.review;
  const maxTick = Math.max(1, frames.maxTick);
  const shownTick = review.active ? review.tick : (view?.tick ?? 0);
  const live = !review.active;
  const marks = useMemo(
    () => collectMarks({ frames: frames.frames, marks: view?.marks }),
    [frames.frames, view?.marks],
  );

  const seekFromEvent = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    frames.openAt(Math.round(ratio * maxTick));
  };

  const onTrackMove = (event) => {
    if (event.buttons === 0) return;
    seekFromEvent(event);
  };

  return (
    <div className="stage-timeline">
      <div className="stage-timeline__head">
        <span className={`stage-timeline__live${live ? " is-live" : ""}`}>
          <Radio size={11} /> {live ? "LIVE" : "REVIEW"}
        </span>
        <span className="stage-mono">TICK {shownTick} / {frames.maxTick}</span>
        {frames.loading ? <span className="stage-mono">加载帧…</span> : null}
        {marks.length ? <span className="stage-timeline__count">{marks.length} 事件</span> : null}
        <span className="stage-grow" />
        {!live ? (
          <>
            <button type="button" className="lab-icon-btn lab-icon-btn--bare" title="上一帧"
              onClick={() => frames.step(-1)}><SkipBack size={13} /></button>
            <button type="button" className="lab-icon-btn lab-icon-btn--bare"
              title={review.playing ? "暂停" : "播放"}
              onClick={() => (review.playing ? frames.pause() : frames.play())}>
              {review.playing ? <Pause size={13} /> : <Play size={13} />}
            </button>
            <button type="button" className="lab-icon-btn lab-icon-btn--bare" title="下一帧"
              onClick={() => frames.step(1)}><SkipForward size={13} /></button>
            <select className="lab-select stage-timeline__speed" value={review.speed}
              onChange={(event) => frames.setSpeed(Number(event.target.value))}>
              {SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
            </select>
          </>
        ) : null}
        <button
          type="button"
          className={`stage-timeline__tolive${live ? " is-live" : ""}`}
          disabled={live}
          onClick={frames.backToLive}
        >
          回到直播
        </button>
      </div>
      <div className="stage-timeline__rail">
        <div
          className="stage-timeline__track"
          role="slider"
          aria-label="对局时间线"
          aria-valuemin={0}
          aria-valuemax={frames.maxTick}
          aria-valuenow={shownTick}
          tabIndex={0}
          onPointerDown={seekFromEvent}
          onPointerMove={onTrackMove}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") { event.preventDefault(); frames.step(-1); }
            if (event.key === "ArrowRight") { event.preventDefault(); frames.step(1); }
          }}
        >
          {frames.buffered.map(([start, end]) => (
            <span
              key={`${start}-${end}`}
              className="stage-timeline__buffered"
              style={{ left: `${pct(start, maxTick)}%`, width: `${Math.max(0.5, pct(end - start, maxTick))}%` }}
            />
          ))}
          <span className="stage-timeline__playhead" style={{ left: `${pct(shownTick, maxTick)}%` }} />
        </div>
        {marks.length ? (
          <div className="stage-timeline__marks">
            {marks.map((mark) => (
              <button
                key={mark.tick}
                type="button"
                tabIndex={-1}
                className={`stage-timeline__mark stage-timeline__mark--${mark.tone}`}
                style={{ left: `${pct(mark.tick, maxTick)}%` }}
                title={mark.label}
                aria-label={mark.label}
                onClick={() => frames.openAt(mark.tick)}
              />
            ))}
          </div>
        ) : null}
      </div>
      {frames.error ? <div className="stage-timeline__error">{frames.error.message || "帧加载失败"}</div> : null}
    </div>
  );
}
