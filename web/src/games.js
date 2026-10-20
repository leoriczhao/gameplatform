/* 游戏目录/元数据助手（13 G4）：通用渲染与交互都按游戏包的 game.yaml 声明驱动。 */
import { getJson } from "./api.js";

let _catalog = null;

export async function catalog() {
  if (!_catalog) {
    _catalog = await getJson("/api/games").then((d) => d.games || []);
  }
  return _catalog;
}

export async function gameMeta(slug) {
  const games = await catalog();
  return games.find((g) => g.id === slug) || null;
}

/* 通用「相对转向」键盘映射（12 §3 controls.mode=relative-turn）：
   上/右/下/左 在屏幕顺序 = [0,3,1,2]（y 向下），相对动作 0=左转 1=直行 2=右转。 */
const KCW = [0, 3, 1, 2];

export function relativeAction(cur, desired) {
  if (cur === desired) return 1;
  const idx = KCW.indexOf(cur);
  if (KCW[(idx + 3) % 4] === desired) return 0;
  if (KCW[(idx + 1) % 4] === desired) return 2;
  return null; // 180° 反向：忽略
}
