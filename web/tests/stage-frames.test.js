import test from "node:test";
import assert from "node:assert/strict";
import {
  bufferedRanges, createFrameBuffer, frameAt, hasMore, loadedThrough, mergeFramePage,
} from "../src/stage/frameBuffer.js";

function frame(tick, value = tick) {
  return { tick, frame: { n: value }, actions: null, events: [] };
}

test("frame pages merge by tick, keep order and track the cursor", () => {
  let buffer = createFrameBuffer();
  assert.equal(hasMore(buffer), true);
  buffer = mergeFramePage(buffer, { frames: [frame(0), frame(1)], next: 2, total: 6 });
  assert.equal(buffer.frames.length, 2);
  assert.equal(buffer.next, 2);
  assert.equal(buffer.total, 6);
  buffer = mergeFramePage(buffer, { frames: [frame(2), frame(3)], next: null, total: 6 });
  assert.deepEqual(buffer.frames.map((item) => item.tick), [0, 1, 2, 3]);
  assert.equal(hasMore(buffer), false);
  // 重复页不会产生重复帧，旧帧以新数据为准
  const updated = mergeFramePage(buffer, { frames: [frame(1, 99)], next: null, total: 4 });
  assert.equal(updated.frames.length, 4);
  assert.equal(updated.frames[1].frame.n, 99);
  assert.equal(loadedThrough(updated), 3);
});

test("frameAt finds the last frame at or before the target", () => {
  const buffer = mergeFramePage(createFrameBuffer(), {
    frames: [frame(0), frame(2), frame(5)], next: null, total: 3,
  });
  assert.equal(frameAt(buffer, 0).tick, 0);
  assert.equal(frameAt(buffer, 1).tick, 0);
  assert.equal(frameAt(buffer, 2).tick, 2);
  assert.equal(frameAt(buffer, 4).tick, 2);
  assert.equal(frameAt(buffer, 99).tick, 5);
  assert.equal(frameAt(createFrameBuffer(), 3), null);
});

test("bufferedRanges groups contiguous ticks for the timeline", () => {
  assert.deepEqual(bufferedRanges(createFrameBuffer()), []);
  const buffer = mergeFramePage(createFrameBuffer(), {
    frames: [frame(0), frame(1), frame(4), frame(5), frame(6), frame(9)],
    next: null, total: 6,
  });
  assert.deepEqual(bufferedRanges(buffer), [[0, 1], [4, 6], [9, 9]]);
});
