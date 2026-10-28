/* 出招控件分型（docs/design/17 §7.3 ControlDock）。

   输入只来自游戏包声明，不在前端按游戏名硬编码：
     pvp.action=unit 或 contract.protocol=composite → CompositeBuilder
     controls.keys                                 → KeyControls
     pvp.choices / choices                         → ChoiceControls
     contract.out_shape 末维                         → DiscreteControls
   都没有就只读（观战、回放、无动作声明的包）。 */

export const CONTROL_NONE = "none";

export function pickControls(meta, view) {
  const m = meta || {};
  const pvp = m.pvp || {};
  const contract = m.contract || {};
  const seats = view?.seats?.length ?? 0;

  if (pvp.action === "unit" || String(contract.protocol || "").toLowerCase() === "composite") {
    return { kind: "composite" };
  }
  if (m.controls && m.controls.keys && Object.keys(m.controls.keys).length) {
    return { kind: "keys", controls: m.controls };
  }
  const choices = (Array.isArray(pvp.choices) && pvp.choices.length) ? pvp.choices
    : (Array.isArray(m.choices) && m.choices.length ? m.choices : []);
  if (choices.length) return { kind: "choices", choices };

  const outShape = contract.out_shape;
  const last = Array.isArray(outShape) ? Number(outShape[outShape.length - 1]) : NaN;
  if (Number.isFinite(last) && last > 0) return { kind: "discrete", count: Math.floor(last) };

  return { kind: CONTROL_NONE, seats };
}
