/* 连接中断横幅（docs/design/17 §7.3 覆盖层优先级 1）。 */

export default function ConnectionBanner({ connection, view }) {
  const state = connection?.state;
  if (state !== "reconnecting" && state !== "closed" && state !== "failed") return null;
  const cached = view?.tick != null ? ` · 已缓存到 tick ${view.tick}` : "";
  const text = state === "failed"
    ? `无法连接对局（HTTP ${connection.status || "?"}）`
    : state === "reconnecting"
      ? `正在重连${cached}`
      : "连接已断开";
  return (
    <div className={`stage-banner${state === "failed" ? " is-error" : ""}`} role="status">
      <span className={`stage-banner__dot${state === "reconnecting" ? " is-pulsing" : ""}`} />
      {text}
      {state === "failed" ? (
        <button type="button" className="stage-banner__link" onClick={() => window.location.reload()}>
          刷新页面
        </button>
      ) : null}
    </div>
  );
}
