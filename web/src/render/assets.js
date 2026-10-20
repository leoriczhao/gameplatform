/* 渲染 v2 · 资源 URL 构造 + 预加载缓存（docs/design/16 §4.2、§6）。
   URL：/api/ugc/assets/{slug}/{meta.version}/{file}
   后端资源路由可能尚未上线：加载失败一律静默降级到 glyph，绝不抛异常、绝不阻塞渲染。
   本模块不依赖 DOM，可在 node --test 下直接 import。 */

import { isSafeAssetPath } from "./paths.js";

export const ASSET_BASE = "/api/ugc/assets";

/* 构造资源 URL；slug/version/file 任一非法返回 null（调用方静默跳过）。 */
export function assetUrl(ctx, file) {
  const slug = ctx && typeof ctx.slug === "string" ? ctx.slug : "";
  const version = ctx && typeof ctx.version === "string" ? ctx.version : "";
  if (!slug || !version) return null;
  if (!isSafeAssetPath(file)) return null;
  const path = file.split("/").map((part) => encodeURIComponent(part)).join("/");
  return ASSET_BASE + "/" + encodeURIComponent(slug) + "/" + encodeURIComponent(version) + "/" + path;
}

export function imageSize(img) {
  if (!img) return { w: 0, h: 0 };
  const w = Number(img.naturalWidth || img.width || 0);
  const h = Number(img.naturalHeight || img.height || 0);
  return { w: Number.isFinite(w) ? w : 0, h: Number.isFinite(h) ? h : 0 };
}

export function isImageReady(img) {
  const { w, h } = imageSize(img);
  return w > 0 && h > 0;
}

function loadViaImageElement(url) {
  return new Promise((resolve, reject) => {
    if (typeof Image === "undefined") { reject(new Error("no Image")); return; }
    let img;
    try { img = new Image(); } catch (err) { reject(err); return; }
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image load failed"));
    try {
      img.decoding = "async";
      img.src = url;
    } catch (err) { reject(err); }
  });
}

async function loadImage(url) {
  // 优先 fetch + createImageBitmap（可精确控制缓存与解码），失败回退 <img>。
  if (typeof fetch === "function" && typeof createImageBitmap === "function") {
    try {
      const res = await fetch(url, { cache: "force-cache", credentials: "same-origin" });
      if (!res || !res.ok) throw new Error("http " + (res ? res.status : "0"));
      const blob = await res.blob();
      const bitmap = await createImageBitmap(blob);
      if (isImageReady(bitmap)) return bitmap;
      if (typeof bitmap.close === "function") bitmap.close();
      throw new Error("empty bitmap");
    } catch (err) { /* 回退 <img> */ }
  }
  return loadViaImageElement(url);
}

/* name → ImageBitmap/HTMLImageElement 缓存；失败的资源记入 failed 不再重试。 */
export class AssetCache {
  constructor() {
    this.images = new Map();
    this.failed = new Set();
    this.pending = new Map();
    this.closed = false;
  }

  get(name) {
    const img = this.images.get(name);
    return img && isImageReady(img) ? img : null;
  }

  has(name) {
    return this.images.has(name);
  }

  hasFailed(name) {
    return this.failed.has(name);
  }

  load(name, url) {
    if (this.closed || !url || !name) return Promise.resolve(null);
    if (this.images.has(name)) return Promise.resolve(this.images.get(name));
    if (this.failed.has(name)) return Promise.resolve(null);
    if (this.pending.has(name)) return this.pending.get(name);
    const task = loadImage(url)
      .then((img) => {
        if (this.closed) {
          if (img && typeof img.close === "function") img.close();
          return null;
        }
        this.images.set(name, img);
        return img;
      })
      .catch(() => {
        this.failed.add(name);
        return null;                       // 静默降级
      })
      .finally(() => { this.pending.delete(name); });
    this.pending.set(name, task);
    return task;
  }

  /* 预加载 meta.assets；返回成功加载数量。失败/非法 URL 不抛异常。 */
  preload(ctx, assets) {
    const jobs = [];
    if (!assets || typeof assets !== "object") return Promise.resolve(0);
    Object.keys(assets).forEach((name) => {
      const url = assetUrl(ctx, assets[name] && assets[name].file);
      if (!url) return;
      jobs.push(this.load(name, url).then((img) => (img ? 1 : 0)).catch(() => 0));
    });
    return Promise.all(jobs).then((rs) => rs.reduce((a, b) => a + b, 0));
  }

  close() {
    this.closed = true;
    this.images.forEach((img) => {
      if (img && typeof img.close === "function") {
        try { img.close(); } catch (err) { /* ignore */ }
      }
    });
    this.images.clear();
    this.pending.clear();
  }
}

export function createAssetCache() {
  return new AssetCache();
}
