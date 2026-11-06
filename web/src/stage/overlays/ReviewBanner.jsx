/* 回看横幅（docs/design/17 §7.3 覆盖层优先级 2）。 */

export default function ReviewBanner({ frames }) {
  if (!frames.review.active) return null;
  return (
    <div className="stage-banner stage-banner--review" role="status">
      <span className="stage-banner__dot" />
      回看中 · tick {frames.review.tick} · 按 Esc 回到直播
      <button type="button" className="stage-banner__link" onClick={frames.backToLive}>
        回到直播
      </button>
    </div>
  );
}
