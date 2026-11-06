import test from "node:test";
import assert from "node:assert/strict";
import { pickControls, CONTROL_NONE } from "../src/stage/controls/pickControls.js";

const twoSeats = { seats: [{ seat: "p0" }, { seat: "p1" }] };

test("composite wins over keys and choices", () => {
  const picked = pickControls({
    pvp: { enabled: true, action: "unit" },
    contract: { protocol: "composite", out_shape: [1, 140] },
    controls: { keys: { ArrowUp: [0, "上"] } },
  }, twoSeats);
  assert.equal(picked.kind, "composite");
});

test("declared keys pick KeyControls even when the action space is discrete", () => {
  const picked = pickControls({
    controls: { mode: "relative-turn", direction_field: "direction", keys: { ArrowUp: [0, "上"] } },
    contract: { out_shape: [1, 3] },
  }, twoSeats);
  assert.equal(picked.kind, "keys");
  assert.equal(picked.controls.mode, "relative-turn");
});

test("pvp choices and generic choices both pick ChoiceControls", () => {
  assert.equal(pickControls({ pvp: { choices: ["石头", "布"] } }, twoSeats).kind, "choices");
  assert.equal(pickControls({ choices: ["A", "B"] }, twoSeats).kind, "choices");
});

test("out_shape falls back to DiscreteControls and hears the last dimension", () => {
  const picked = pickControls({ contract: { out_shape: [1, 2, 9] } }, twoSeats);
  assert.equal(picked.kind, "discrete");
  assert.equal(picked.count, 9);
});

test("a package without any action declaration is read-only", () => {
  const picked = pickControls({ board: {} }, twoSeats);
  assert.equal(picked.kind, CONTROL_NONE);
});
