import { createOpenEnvClient } from "./openenv.js";

/* Reconstruct in one WS environment pinned to the recorded version/options. */
export async function rebuildReplay(replay, { createClient = createOpenEnvClient, onProgress, signal } = {}) {
  if (replay.schema_version !== 1 || !replay.game_version || replay.seed == null) {
    throw new Error("该回放缺少受支持的版本或 seed，无法可靠重建");
  }
  if (replay.moves.length >= 2000) throw new Error("回放超过 2000 帧限制");
  const check = () => { if (signal?.aborted) throw new DOMException("Aborted", "AbortError"); };
  const gameState = (result) => {
    if (result?.observation?.state == null) throw new Error("环境未返回完整回放局面");
    return result.observation.state;
  };
  check();
  const env = createClient(replay.game, { signal });
  try {
    const initial = await env.reset({
      seed: replay.seed,
      version: replay.game_version,
      ...(replay.options != null ? { options: replay.options } : {}),
      include_state: true,
    });
    check();
    // state() after reset describes this episode, not the currently published package.
    const snap = await env.state();
    check();
    const info = snap?.environment;
    if (!info?.version) throw new Error("环境 state 未返回 environment，无法核对回放版本");
    if (info.version !== replay.game_version) throw new Error("环境版本与回放不一致");
    const states = [gameState(initial)];
    const progressMeta = info.meta || {};
    onProgress?.(states.slice(), progressMeta);
    for (const move of replay.moves) {
      check();
      const action = move.opponent != null ? { p0: move.action, p1: move.opponent } : move.action;
      const result = await env.step(action);
      check();
      states.push(gameState(result));
      if (states.length % 16 === 0) onProgress?.(states.slice(), progressMeta);
    }
    check();
    onProgress?.(states.slice(), progressMeta);
    check();
    return states;
  } finally {
    env.close();
  }
}
