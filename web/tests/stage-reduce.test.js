import test from "node:test";
import assert from "node:assert/strict";
import {
  applySnapshot, findSeat, isLiveStatus, isTerminalStatus, reduceAll, reduceMatch, seatTone,
} from "../src/stage/reduceMatch.js";

const NOW = 1_700_000_000_000;

function snapshot(overrides = {}) {
  return {
    type: "snapshot",
    seq: 7,
    server_time: NOW + 250,
    id: "abcdefabcdef",
    game: "snake",
    version: "1.2.0",
    kind: "pvp",
    mode: "ranked",
    visibility: "public",
    invite: null,
    clock: { kind: "turn", move_timeout_s: 30, on_timeout: "empty", max_timeouts: 5 },
    status: "active",
    result: null,
    seats: [
      { seat: "p0", occupant: { user_id: 1, name: "leoric" }, controller: { type: "human" },
        presence: "online", submitted: false, timeouts: 0 },
      { seat: "p1", occupant: { user_id: 2, name: "maria" }, controller: { type: "human" },
        presence: "online", submitted: false, timeouts: 0 },
    ],
    you: { seat: "p0" },
    tick: 3,
    frame: { cells: [] },
    events: [{ name: "eat" }],
    to_act: ["p0"],
    deadline_at: 1_700_000_030,
    frames: 4,
    created_at: 1_700_000_000,
    rematch: null,
    chat: [],
    ...overrides,
  };
}

test("snapshot becomes the authoritative MatchView and estimates the clock offset", () => {
  const view = reduceMatch(null, snapshot(), NOW);
  assert.equal(view.id, "abcdefabcdef");
  assert.equal(view.tick, 3);
  assert.equal(view.frame_count, 4);
  assert.deepEqual(view.you, { seat: "p0" });
  assert.equal(view.seats.length, 2);
  assert.equal(view.seats[0].occupant.name, "leoric");
  assert.equal(view.seq, 7);
  assert.equal(view.server_offset_ms, 250);
  assert.equal(isLiveStatus(view.status), true);
});

test("snapshot normalizes missing seat fields and falls back to tick + 1 for the frame count", () => {
  const view = reduceMatch(null, {
    type: "snapshot", status: "waiting", tick: 0, seats: [{ seat: "p0" }],
  }, NOW);
  assert.deepEqual(view.seats[0], {
    seat: "p0", occupant: null, controller: { type: "human" }, presence: "offline",
    submitted: false, timeouts: 0,
  });
  assert.equal(view.frame_count, 1);
  assert.equal(view.you.seat, null);
});

test("tick advances the frame and clears the previous tick's submissions", () => {
  const start = reduceMatch(null, snapshot(), NOW);
  const submitted = reduceMatch(start, { type: "submitted", seq: 8, seat: "p0", tick: 3 }, NOW);
  assert.equal(findSeat(submitted, "p0").submitted, true);
  const next = reduceMatch(submitted, {
    type: "tick", seq: 9, tick: 4, frame: { cells: [1] }, actions: { p0: 1, p1: 0 },
    events: [{ name: "move" }], to_act: ["p1"], deadline_at: 1_700_000_040,
  }, NOW);
  assert.equal(next.tick, 4);
  assert.deepEqual(next.frame, { cells: [1] });
  assert.deepEqual(next.to_act, ["p1"]);
  assert.deepEqual(next.actions, { p0: 1, p1: 0 });
  assert.equal(findSeat(next, "p0").submitted, false);
  assert.equal(next.frame_count, 5);
});

test("a stale tick or a submission for an old tick only advances the cursor", () => {
  const view = reduceMatch(null, snapshot(), NOW);
  const stale = reduceMatch(view, { type: "tick", seq: 10, tick: 2, frame: {} }, NOW);
  assert.equal(stale.tick, 3);
  assert.equal(stale.seq, 10);
  const late = reduceMatch(view, { type: "submitted", seq: 11, seat: "p1", tick: 2 }, NOW);
  assert.equal(findSeat(late, "p1").submitted, false);
  assert.equal(late.seq, 11);
});

test("timeout records the count on the seat", () => {
  const view = reduceMatch(null, snapshot(), NOW);
  const next = reduceMatch(view, { type: "timeout", seq: 8, seat: "p0", tick: 3, count: 2, max: 5 }, NOW);
  assert.equal(findSeat(next, "p0").timeouts, 2);
  assert.equal(findSeat(next, "p0").submitted, false);
});

test("seat events merge into the existing seat (join, leave, presence, controller)", () => {
  const view = reduceMatch(null, snapshot({ status: "waiting", seats: [
    { seat: "p0", occupant: { user_id: 1, name: "leoric" }, controller: { type: "human" },
      presence: "online", submitted: false, timeouts: 0 },
    { seat: "p1", occupant: null, controller: { type: "human" },
      presence: "empty", submitted: false, timeouts: 0 },
  ] }), NOW);
  const joined = reduceMatch(view, {
    type: "seat", seq: 8, seat: "p1", occupant: { user_id: 2, name: "maria" },
    controller: { type: "human" }, presence: "online", submitted: false, timeouts: 0,
  }, NOW);
  assert.equal(findSeat(joined, "p1").occupant.name, "maria");
  assert.equal(joined.seats.length, 2);
  const offline = reduceMatch(joined, { type: "seat", seq: 9, seat: "p1",
    occupant: { user_id: 2, name: "maria" }, controller: { type: "human" },
    presence: "offline", submitted: false, timeouts: 0 }, NOW);
  assert.equal(findSeat(offline, "p1").presence, "offline");
});

test("status finished clears the pending tick and keeps the result", () => {
  const view = reduceMatch(null, snapshot(), NOW);
  const finished = reduceMatch(view, {
    type: "status", seq: 12, status: "finished",
    result: { winner: "p0", cause: "done", tick: 9 },
  }, NOW);
  assert.equal(finished.status, "finished");
  assert.equal(finished.result.winner, "p0");
  assert.deepEqual(finished.to_act, []);
  assert.equal(finished.deadline_at, null);
  assert.equal(isTerminalStatus(finished.status), true);
});

test("rematch and ping keep their own places", () => {
  const view = reduceMatch(null, snapshot(), NOW);
  const offered = reduceMatch(view, {
    type: "rematch", seq: 13, rematch: { state: "offered", by: "p1", expires_at: NOW / 1000 + 60 },
  }, NOW);
  assert.equal(offered.rematch.state, "offered");
  const ping = reduceMatch(offered, { type: "ping", server_time: NOW + 1250 }, NOW);
  assert.equal(ping.seq, 13);
  assert.equal(ping.server_offset_ms, 1250);
});

test("snapshot chat becomes the authoritative history (normalized and deduped)", () => {
  const view = reduceMatch(null, snapshot({ chat: [
    { id: 1, from: 1, name: "leoric", seat: "p0", text: "hi", at: NOW, tick: 0 },
    { id: 2, from: 2, name: "maria", seat: "p1", text: "yo", at: NOW + 1000, tick: 1 },
    { id: 2, from: 2, name: "maria", seat: "p1", text: "dup", at: NOW + 1000, tick: 1 },
  ] }), NOW);
  assert.equal(view.chat.length, 2);
  assert.deepEqual(view.chat[1], {
    id: 2, from: 2, name: "maria", seat: "p1", text: "yo", at: NOW + 1000, tick: 1,
  });
});

test("a snapshot without chat keeps the chat we already have", () => {
  const first = reduceMatch(null, snapshot({ chat: [
    { id: 1, from: 1, text: "hi", at: NOW, tick: 0 },
  ] }), NOW);
  // 服务端对非双方（如观战者）可能不带 chat 字段：此时保留客户端已有列表
  const next = reduceMatch(first, snapshot({ seq: 8, chat: undefined }), NOW);
  assert.equal(next.seq, 8);
  assert.equal(next.chat.length, 1);
  assert.equal(next.chat[0].text, "hi");
});

test("chat events append by id, dedupe duplicates and keep the latest 200", () => {
  let view = reduceMatch(null, snapshot(), NOW);
  for (let i = 1; i <= 250; i += 1) {
    view = reduceMatch(view, {
      type: "chat", seq: 10 + i,
      message: { id: i, from: i % 2 ? 1 : 2, text: `m${i}`, at: NOW, tick: i },
    }, NOW);
  }
  assert.equal(view.chat.length, 200);
  assert.equal(view.chat[0].id, 51);
  assert.equal(view.chat[199].id, 250);
  const duplicate = reduceMatch(view, {
    type: "chat", seq: 999,
    message: { id: 250, from: 1, text: "dup", at: NOW, tick: 251 },
  }, NOW);
  assert.equal(duplicate.chat.length, 200);
  assert.equal(duplicate.chat[199].text, "m250");
});

test("chat events normalize the legacy REST shape and flat payloads", () => {
  // 平铺：字段直接在事件上（兼容不同后端实现）
  const flat = reduceMatch(reduceMatch(null, snapshot(), NOW), {
    type: "chat", seq: 20, id: 7, user_id: 2, nickname: "maria", seat: "p1",
    text: "hey", created_at: NOW,
  }, NOW);
  assert.equal(flat.chat[0].from, 2);
  assert.equal(flat.chat[0].name, "maria");
  assert.equal(flat.chat[0].seat, "p1");
  assert.equal(flat.chat[0].at, NOW);
  // event.message 用旧 REST 形状（user_id / nickname / created_at）
  const legacy = reduceMatch(flat, { type: "chat", seq: 21,
    message: { id: 8, user_id: 1, nickname: "leoric", text: "yo", created_at: NOW } }, NOW);
  assert.equal(legacy.chat.length, 2);
  assert.equal(legacy.chat[1].from, 1);
  assert.equal(legacy.chat[1].name, "leoric");
});

test("the log keeps tick / submit / status entries for the side panel", () => {
  let view = reduceMatch(null, snapshot(), NOW);
  view = reduceMatch(view, { type: "submitted", seq: 8, seat: "p0", tick: 3 }, NOW);
  view = reduceMatch(view, { type: "tick", seq: 9, tick: 4, frame: { n: 4 },
    to_act: ["p1"], deadline_at: null, events: [{ name: "eat" }] }, NOW);
  view = reduceMatch(view, { type: "status", seq: 10, status: "finished",
    result: { winner: "p0", cause: "done" } }, NOW);
  assert.deepEqual(view.log.map((entry) => entry.kind), ["submit", "tick", "status"]);
  assert.equal(view.log[1].tick, 4);
  assert.equal(view.log[1].events[0].name, "eat");
});

test("reduceAll replays a backlog in order; unknown events only move the cursor", () => {
  const view = reduceAll(null, [
    snapshot(),
    { type: "tick", seq: 8, tick: 4, frame: { n: 4 }, to_act: ["p1"], deadline_at: null },
    { type: "future-thing", seq: 9 },
  ], NOW);
  assert.equal(view.tick, 4);
  assert.equal(view.seq, 9);
  assert.equal(seatTone("p0"), "cyan");
  assert.equal(seatTone("p1"), "violet");
  assert.equal(seatTone("p2"), "neutral");
});
