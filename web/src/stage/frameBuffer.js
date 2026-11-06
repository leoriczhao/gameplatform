/* 帧缓冲（docs/design/17 §7.3 Timeline、§7.6 useFrames）。

   `/api/v2/matches/{id}/frames?from&limit` 返回 `{frames, next, total}`：
   `from` 是**数组下标**不是 tick；帧上的 `tick` 是权威时间轴。分页的
   `next` 为 null 表示已经加载到末尾。这里只做纯数据合并，网络请求在
   useFrames 里。 */

export function createFrameBuffer() {
  return { frames: [], total: 0, next: 0 };
}

export function mergeFramePage(buffer, page) {
  const incoming = Array.isArray(page?.frames) ? page.frames : [];
  const byTick = new Map(buffer.frames.map((frame) => [frame.tick, frame]));
  for (const frame of incoming) {
    if (frame && Number.isFinite(frame.tick)) byTick.set(frame.tick, frame);
  }
  const frames = [...byTick.values()].sort((a, b) => a.tick - b.tick);
  const total = Number.isFinite(page?.total) ? page.total : Math.max(buffer.total, frames.length);
  const next = page && Object.prototype.hasOwnProperty.call(page, "next") ? page.next : buffer.next;
  return { frames, total, next };
}

/* 已加载到哪个 tick（没有帧时 -1），用于判断回看目标是否还需要拉取。 */
export function loadedThrough(buffer) {
  return buffer.frames.length ? buffer.frames[buffer.frames.length - 1].tick : -1;
}

export function hasMore(buffer) {
  return buffer.next !== null && buffer.next !== undefined;
}

/* tick <= target 的最后一帧；目标早于第一帧时退回第一帧。 */
export function frameAt(buffer, target) {
  if (!buffer.frames.length) return null;
  let found = buffer.frames[0];
  for (const frame of buffer.frames) {
    if (frame.tick > target) break;
    found = frame;
  }
  return found;
}

/* 连续帧合成区间，时间线上用浅色标出已缓冲部分。 */
export function bufferedRanges(buffer) {
  const ranges = [];
  for (const frame of buffer.frames) {
    const last = ranges[ranges.length - 1];
    if (last && frame.tick <= last[1] + 1) last[1] = Math.max(last[1], frame.tick);
    else ranges.push([frame.tick, frame.tick]);
  }
  return ranges;
}
