import test from "node:test";
import assert from "node:assert/strict";
import {
  collectMarks, markText, markTone, MAX_MARK_TICKS,
} from "../src/stage/timelineMarks.js";
import { reduceMatch } from "../src/stage/reduceMatch.js";

function frame(tick, events = [], marks = []) {
  return { tick, frame: {}, actions: null, events, marks };
}

test("frame engine events become ticks grouped by tick", () => {
  const marks = collectMarks({
    frames: [frame(0), frame(3, ["eat"]), frame(9, ["attack", "death"])],
  });
  assert.deepEqual(marks.map((item) => item.tick), [3, 9]);
  assert.equal(marks[0].label, "#3 吃到食物");
  assert.equal(marks[0].tone, "good");
  assert.equal(marks[1].label, "#9 攻击 · 死亡");
  assert.equal(marks[1].tone, "danger");
  assert.equal(marks[1].items.length, 2);
});

test("server marks (timeout/chat/resign) merge with frame events", () => {
  const marks = collectMarks({
    frames: [frame(2, [], [{ id: 1, tick: 2, kind: "timeout", seat: "p1" }]),
             frame(4, ["attack"])],
    marks: [
      { id: 1, tick: 2, kind: "timeout", seat: "p1" },
      { id: 2, tick: 6, kind: "chat", seat: "p0" },
      { id: 3, tick: 8, kind: "resign", seat: "p1" },
    ],
  });
  assert.deepEqual(marks.map((item) => item.tick), [2, 4, 6, 8]);
  assert.equal(marks[0].tone, "warn");
  assert.equal(marks[0].items.length, 1, "same mark id from frames and view dedupes");
  assert.equal(marks[2].label, "#6 聊天");
  assert.equal(marks[2].tone, "info");
  assert.equal(marks[3].tone, "warn");
});

test("live marks work before any frame has been buffered", () => {
  const marks = collectMarks({
    frames: [],
    marks: [{ id: 7, tick: 11, kind: "timeout" }],
  });
  assert.deepEqual(marks.map((item) => item.tick), [11]);
});

test("unknown kinds fall back to the kind name and info tone", () => {
  assert.equal(markText("levelup"), "levelup");
  assert.equal(markTone("levelup"), "info");
  assert.equal(markText(null), "事件");
});

test("marks keep the latest MAX_MARK_TICKS ticks", () => {
  const frames = Array.from({ length: MAX_MARK_TICKS + 20 }, (_, tick) =>
    frame(tick, ["eat"]));
  const marks = collectMarks({ frames });
  assert.equal(marks.length, MAX_MARK_TICKS);
  assert.equal(marks[0].tick, 20);
  assert.equal(marks[marks.length - 1].tick, MAX_MARK_TICKS + 19);
});

test("reducer keeps snapshot marks and appends mark events by id", () => {
  const snapshot = {
    type: "snapshot", seq: 3, id: "m1", game: "snake", status: "active",
    tick: 5, frames: 6, marks: [{ id: 1, tick: 2, kind: "timeout" }],
  };
  let view = reduceMatch(null, snapshot, 0);
  assert.deepEqual(view.marks.map((item) => item.id), [1]);
  view = reduceMatch(view, { type: "mark", seq: 4, id: 2, tick: 5, kind: "chat", seat: "p0" }, 0);
  assert.deepEqual(view.marks.map((item) => item.id), [1, 2]);
  view = reduceMatch(view, { type: "mark", seq: 4, id: 2, tick: 5, kind: "chat", seat: "p0" }, 0);
  assert.deepEqual(view.marks.map((item) => item.id), [1, 2], "duplicate mark id ignored");
  assert.equal(view.seq, 4);
});
