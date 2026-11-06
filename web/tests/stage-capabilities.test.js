import test from "node:test";
import assert from "node:assert/strict";
import {
  CLOCK_COUNTDOWN, CLOCK_FINAL, CLOCK_REALTIME, CLOCK_REVIEW, CLOCK_TICK,
  canChat, clockMode, deriveCapabilities, humanSeats, openSeats, opponentSeat,
  remainingMs,
} from "../src/stage/capabilities.js";

const NOW = 1_700_000_000_000;
const OFFSET = 250;

function view(overrides = {}) {
  return {
    id: "abcdefabcdef", game: "snake", kind: "pvp", mode: "ranked", visibility: "public",
    clock: { kind: "turn", move_timeout_s: 30 }, status: "active", result: null,
    seats: [
      { seat: "p0", occupant: { user_id: 1, name: "leoric" }, controller: { type: "human" },
        presence: "online", submitted: false, timeouts: 0 },
      { seat: "p1", occupant: { user_id: 2, name: "maria" }, controller: { type: "human" },
        presence: "online", submitted: false, timeouts: 0 },
    ],
    you: { seat: "p0" }, tick: 3, frame: {}, events: [], to_act: ["p0"],
    deadline_at: (NOW + OFFSET) / 1000 + 18, server_offset_ms: OFFSET,
    ...overrides,
  };
}

test("my turn: can act, countdown uses the deadline minus the clock offset", () => {
  const caps = deriveCapabilities(view(), { now: NOW });
  assert.equal(caps.canAct, true);
  assert.equal(caps.myTurn, true);
  assert.equal(caps.showClock, true);
  assert.equal(caps.clockMode, CLOCK_COUNTDOWN);
  assert.equal(caps.remainingMs, 18_000);
  assert.equal(caps.readOnlyReason, null);
  assert.equal(caps.showTimeline, false);
  assert.equal(caps.showShare, true);
});

test("my turn is false while I already submitted but the dock may still edit", () => {
  const v = view();
  v.seats[0] = { ...v.seats[0], submitted: true };
  const caps = deriveCapabilities(v, { now: NOW });
  assert.equal(caps.canAct, true);          // turn 模式下结算前还能改
  assert.equal(caps.submittedThisTick, true);
});

test("waiting for the opponent, spectator and autopilot each have their own reason", () => {
  const waiting = deriveCapabilities(view({ to_act: ["p1"] }), { now: NOW });
  assert.equal(waiting.canAct, false);
  assert.equal(waiting.readOnlyReason, "等待对手出手");

  const spectator = deriveCapabilities(view({ you: { seat: null } }), { now: NOW });
  assert.equal(spectator.canAct, false);
  assert.equal(spectator.readOnlyReason, "观战中");
  assert.equal(spectator.showChat, false);
  assert.equal(spectator.showTimeline, false);

  const v = view({ to_act: ["p0"] });
  v.seats[0] = { ...v.seats[0], controller: { type: "model", model_id: 3, name: "dqn-1" } };
  const autopilot = deriveCapabilities(v, { now: NOW });
  assert.equal(autopilot.canAct, false);
  assert.equal(autopilot.readOnlyReason, "托管中");
});

test("waiting room: no countdown, no timeline, invite is shown to the host", () => {
  const v = view({ status: "waiting", to_act: [], deadline_at: null });
  v.seats[1] = { seat: "p1", occupant: null, controller: { type: "human" },
    presence: "empty", submitted: false, timeouts: 0 };
  const caps = deriveCapabilities(v, { now: NOW });
  assert.equal(caps.canAct, false);
  assert.equal(caps.readOnlyReason, "等待对手加入");
  assert.deepEqual(openSeats(v).map((s) => s.seat), ["p1"]);
  assert.equal(clockMode(v), CLOCK_TICK);
  assert.equal(caps.showClock, false);
});

test("realtime and finished matches switch the clock form", () => {
  const realtime = deriveCapabilities(view({
    clock: { kind: "realtime", tick_ms: 250 }, deadline_at: null,
  }), { now: NOW });
  assert.equal(realtime.clockMode, CLOCK_REALTIME);
  assert.equal(realtime.showClock, false);

  const finished = deriveCapabilities(view({ status: "finished", to_act: [], deadline_at: null }), { now: NOW });
  assert.equal(finished.clockMode, CLOCK_FINAL);
  assert.equal(finished.readOnlyReason, "对局已结束");
  assert.equal(finished.showTimeline, true);
  assert.equal(finished.showRematch, true);
});

test("reviewing disables acting and forces the timeline", () => {
  const caps = deriveCapabilities(view(), { reviewing: true, now: NOW });
  assert.equal(caps.canAct, false);
  assert.equal(caps.clockMode, CLOCK_REVIEW);
  assert.equal(caps.readOnlyReason, "回看中");
  assert.equal(caps.showTimeline, true);
  assert.equal(caps.showRematch, false);
});

test("single-seat practice hides chat; private matches hide sharing", () => {
  const practice = view({
    kind: "pve", visibility: "private", seats: [view().seats[0]], to_act: ["p0"],
  });
  const caps = deriveCapabilities(practice, { now: NOW });
  assert.equal(caps.showChat, false);
  assert.equal(caps.showShare, false);
  assert.equal(remainingMs(view({ deadline_at: null }), NOW), null);
});

test("seat helpers stay stable for pvp and practice", () => {
  const v = view();
  assert.equal(opponentSeat(v), "p1");
  assert.equal(humanSeats(v).length, 2);
  assert.equal(canChat(v), true);
  assert.equal(humanSeats(view({ seats: [view().seats[0]] })).length, 1);
  assert.equal(canChat(view({ seats: [view().seats[0]] })), false);
});

test("rematch is only offered on finished human pvp matches", () => {
  const finished = deriveCapabilities(view({ status: "finished", to_act: [] }), { now: NOW });
  assert.equal(finished.showRematch, true);
  const aiSeat = view({ status: "finished", to_act: [] });
  aiSeat.seats[1] = { ...aiSeat.seats[1], controller: { type: "ai", strategy: "dqn" } };
  assert.equal(deriveCapabilities(aiSeat, { now: NOW }).showRematch, false);
});
