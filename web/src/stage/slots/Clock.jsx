/* Clock（docs/design/17 §7.3）：turn + 时限显示环形倒计时，其余显示 TICK。
   倒计时用 deadline_at - (本地时间 + server_offset_ms)；剩 10s 转 amber、5s 转 red。 */

const RING_R = 15;
const RING_C = 2 * Math.PI * RING_R;

export default function Clock({ view, caps, now, tick }) {
  const mode = caps.clockMode;
  const displayTick = tick ?? view?.tick ?? 0;
  const remaining = caps.remainingMs;
  const seconds = remaining == null ? null : Math.ceil(remaining / 1000);
  const limitMs = Number(view?.clock?.move_timeout_s) * 1000;
  const ratio = remaining == null || !limitMs ? 0 : Math.max(0, Math.min(1, remaining / limitMs));
  const tone = seconds != null && seconds <= 5 ? "red" : seconds != null && seconds <= 10 ? "amber" : "normal";

  return (
    <div className={`stage-clock stage-clock--${mode}`}>
      {mode === "countdown" ? (
        <div className={`stage-clock__ring is-${tone}`}>
          <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">
            <circle cx="20" cy="20" r={RING_R} className="stage-clock__ring-bg" />
            <circle
              cx="20" cy="20" r={RING_R}
              className="stage-clock__ring-fg"
              strokeDasharray={RING_C}
              strokeDashoffset={RING_C * (1 - ratio)}
              transform="rotate(-90 20 20)"
            />
          </svg>
          <span className="stage-clock__secs" aria-live="polite">{seconds}s</span>
        </div>
      ) : null}
      <div className="stage-clock__tick">
        <span className="stage-clock__label">{mode === "review" ? "REVIEW" : mode === "final" ? "FINAL" : "TICK"}</span>
        <span className="stage-clock__value">{displayTick}</span>
      </div>
      {mode === "realtime" ? <span className="stage-clock__beat" aria-hidden="true" /> : null}
      {mode === "final" ? <span className="stage-clock__label">已结束</span> : null}
    </div>
  );
}
