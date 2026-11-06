/* HudStrip（docs/design/17 §7.2）：只渲染游戏声明过的 HUD（渲染 v2、D28 不变）。 */

import Hud from "../../render/Hud.jsx";

export default function HudStrip({ meta, frame }) {
  const items = Array.isArray(meta?.hud) ? meta.hud : [];
  if (!items.length) return null;
  return (
    <div className="stage-hud">
      <Hud items={items} state={frame} />
    </div>
  );
}
