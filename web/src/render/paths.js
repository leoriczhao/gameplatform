/* 渲染 v2 · 纯取值与夹紧工具（docs/design/16 §3.6）。
   服务端 meta 是不可信数据：这里只做纯取值，禁止 eval / new Function。
   path 语法：^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*$
   ≤64 字符、≤4 段、不含 __。越界/非法 path 一律返回 undefined。 */

export const PATH_MAX_LEN = 64;
export const PATH_MAX_SEGMENTS = 4;
export const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;

const PATH_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*$/;

export function isValidPath(path) {
  if (typeof path !== "string") return false;
  if (!path.length || path.length > PATH_MAX_LEN) return false;
  if (path.includes("__")) return false;
  if (!PATH_RE.test(path)) return false;
  return path.split(".").length <= PATH_MAX_SEGMENTS;
}

export function pathSegments(path) {
  return isValidPath(path) ? path.split(".") : null;
}

/* 纯取值：只读自身属性，不触发 getter 链上的原型/继承读取。 */
export function getPath(obj, path) {
  const segs = pathSegments(path);
  if (!segs) return undefined;
  let cur = obj;
  for (let i = 0; i < segs.length; i += 1) {
    if (cur === null || cur === undefined) return undefined;
    const t = typeof cur;
    if (t !== "object" && t !== "function") return undefined;
    if (!Object.prototype.hasOwnProperty.call(cur, segs[i])) return undefined;
    cur = cur[segs[i]];
  }
  return cur;
}

/* 第一个取值成功的候选 path（用于 owner_field 缺省 owner/player/side）。 */
export function getFirstPath(obj, paths) {
  for (let i = 0; i < paths.length; i += 1) {
    const v = getPath(obj, paths[i]);
    if (v !== undefined && v !== null) return v;
  }
  return undefined;
}

export function isFiniteNumber(v) {
  return typeof v === "number" && Number.isFinite(v);
}

export function clamp(value, min, max) {
  if (!isFiniteNumber(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

export function clamp01(value, fallback = 0) {
  return isFiniteNumber(value) ? clamp(value, 0, 1) : fallback;
}

/* 数字：非有限值 → fallback（fallback 也夹紧），否则夹紧到 [min,max]。 */
export function numOr(value, fallback, min = -Infinity, max = Infinity) {
  if (!isFiniteNumber(value)) {
    const f = isFiniteNumber(fallback) ? fallback : 0;
    return f < min ? min : f > max ? max : f;
  }
  return value < min ? min : value > max ? max : value;
}

export function intOr(value, fallback, min = -2147483648, max = 2147483647) {
  return Math.round(numOr(value, fallback, min, max));
}

export function strOr(value, fallback = "", maxLen = 64) {
  if (typeof value !== "string") return fallback;
  const s = maxLen > 0 ? value.slice(0, maxLen) : value;
  return s.length ? s : fallback;
}

export function boolOr(value, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

export function pickEnum(value, allowed, fallback = null) {
  return typeof value === "string" && allowed.includes(value) ? value : fallback;
}

export function isHexColor(value) {
  return typeof value === "string" && HEX_COLOR_RE.test(value);
}

/* 颜色只认 #rrggbb；其余（含 CSS 关键字/函数/变量）一律丢弃。 */
export function colorOr(value, fallback = null) {
  return isHexColor(value) ? value.toLowerCase() : fallback;
}

export function isPlainObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/* 按码点截断，避免切开 emoji 代理对。 */
export function truncateChars(value, maxChars) {
  if (typeof value !== "string" || maxChars <= 0) return "";
  const chars = Array.from(value);
  return chars.length <= maxChars ? value : chars.slice(0, maxChars).join("");
}

export function isSafeAssetPath(file) {
  if (typeof file !== "string") return false;
  if (!file.length || file.length > 200) return false;
  if (file.startsWith("/") || file.includes("\\")) return false;
  if (/[\u0000-\u001f\u007f?#%]/.test(file)) return false;
  const parts = file.split("/");
  return parts.every((p) => p.length > 0 && p !== "." && p !== "..");
}

/* 资源名（docs/design/16 §4.1）：^[a-z0-9][a-z0-9_-]{0,23}$ */
export const ASSET_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,23}$/;

export function isAssetName(name) {
  return typeof name === "string" && ASSET_NAME_RE.test(name);
}

/* vector.path 子集（docs/design/16 §3.2）：≤1024、以 M/m 开头、字符白名单。 */
export const VECTOR_PATH_RE = /^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\- ]+$/;

export function isVectorPath(path) {
  if (typeof path !== "string") return false;
  if (path.length < 2 || path.length > 1024) return false;
  if (path[0] !== "M" && path[0] !== "m") return false;
  return VECTOR_PATH_RE.test(path);
}
