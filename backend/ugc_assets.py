"""渲染 v2 资源与沙箱帧服务（设计 16 §4.2 / §5.2）。

- 资源：精确白名单 + 魔数嗅探 Content-Type + 不可变缓存 + nosniff。
- 帧：opaque-origin 文档（CSP sandbox allow-scripts），内联 renderer.js 与资源
  base64，不发起任何网络请求；渲染器跑在 blob Worker + OffscreenCanvas 里。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response

import ugc_pack

CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
}

FRAME_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; "
        "script-src 'unsafe-inline' blob:; worker-src blob:; "
        "img-src data:; connect-src 'none'; style-src 'unsafe-inline'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, max-age=60",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def declared_files(meta: dict) -> dict:
    """相对路径 → 'image'|'sound'（资源路由白名单，16 §4.2）。"""
    out = {}
    for spec in (meta.get("assets") or {}).values():
        out[spec["file"]] = "image"
    for spec in (meta.get("sounds") or {}).values():
        out[spec["file"]] = "sound"
    return out


def _content_type(name: str, data: bytes) -> str:
    try:
        kind, _w, _h = ugc_pack._sniff_image(name, data)
        return "image/png" if kind == "png" else "image/webp"
    except ugc_pack.UGCError:
        pass
    try:
        kind = ugc_pack._sniff_audio(name, data)
    except ugc_pack.UGCError:
        raise HTTPException(415, f"资源类型不受支持：{name}")
    return {"ogg": "audio/ogg", "mp3": "audio/mpeg", "wav": "audio/wav"}[kind]


def asset_response(version: dict, rel: str) -> Response:
    """读取一个已声明资源（拒绝目录遍历与未声明文件）。"""
    meta = version["meta"].get("meta", version["meta"])
    if rel not in declared_files(meta):
        raise HTTPException(404, "资源不存在")
    root = Path(version["package_path"]).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(404, "资源不存在")
    try:
        data = target.read_bytes()
    except OSError:
        raise HTTPException(404, "资源不存在")
    return Response(content=data, media_type=_content_type(rel, data),
                    headers=CACHE_HEADERS)


def renderer_source(version: dict) -> dict:
    """渲染器源码（审核预览用；已开启/未开启都返回）。"""
    stored = version["meta"]
    meta = stored.get("meta", stored)
    rend = meta.get("renderer")
    if not rend:
        return {"renderer": None, "enabled": False}
    try:
        source = (Path(version["package_path"]) / rend["entry"]).read_text(
            encoding="utf-8")
    except OSError:
        source = ""
    return {"renderer": {"entry": rend["entry"], "source": source,
                         "size": len(source.encode("utf-8"))},
            "enabled": bool(stored.get("renderer_enabled")),
            "scan": stored.get("renderer_scan")}


# 帧内引导脚本：建 Worker（blob）→ 转发协议 → 看门狗 → 指针 → 上报。
BOOTSTRAP = r"""
(function () {
  "use strict";
  var cfg;
  try {
    cfg = JSON.parse(document.getElementById("ugc-render-cfg").textContent);
  } catch (e) { return; }
  var canvas = document.getElementById("ugc-board");
  var offscreen;
  try { offscreen = canvas.transferControlToOffscreen(); }
  catch (e) { parent.postMessage({ type: "error", message: "OffscreenCanvas 不可用" }, "*"); return; }

  var worker = null, seq = 0, pending = {}, dead = false, hasInput = false;
  var ready = false, initTimer = 0;
  function toHost(m) { try { parent.postMessage(m, "*"); } catch (e) {} }
  function fail(message) {
    if (dead) return;
    dead = true;
    try { if (worker) worker.terminate(); } catch (e) {}
    toHost({ type: "error", message: String(message) });
  }

  var prelude = [
    '"use strict";',
    'var __state=null,__sprites={},__api=null,__canvas=null;',
    'function __post(m){self.postMessage(m);}',
    'self.onmessage=async function(ev){var d=ev.data||{};try{',
    'if(d.type==="init"){',
    'var c=d.canvas;c.width=Math.max(1,Math.round(d.width*(d.dpr||1)));c.height=Math.max(1,Math.round(d.height*(d.dpr||1)));__canvas=c;var ctx=c.getContext("2d");__sprites={};',
    'for(var n in d.assets){var a=d.assets[n];var b=atob(a.data);var u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);try{__sprites[n]=await createImageBitmap(new Blob([u],{type:a.type}));}catch(e){__sprites[n]=null;}}',
    '__api={ctx:ctx,width:d.width,height:d.height,dpr:d.dpr||1,sprites:__sprites,sprite:function(n){return __sprites[n]||null;},sfx:function(n){__post({type:"sfx",name:n});},cell:function(x,y){__post({type:"cell",x:x,y:y});}};',
    'if(self.Renderer&&typeof self.Renderer.init==="function")self.Renderer.init(__api);',
    '__post({type:"ready",hasInput:!!(self.Renderer&&typeof self.Renderer.input==="function")});return;}',
    'if(d.type==="state"){__state=d.state;return;}',
    'if(d.type==="tick"){if(self.Renderer&&typeof self.Renderer.frame==="function")self.Renderer.frame(__state,d.t,d.dt);__post({type:"ack",seq:d.seq});return;}',
    'if(d.type==="resize"){if(__canvas){__canvas.width=Math.max(1,Math.round(d.width*(d.dpr||1)));__canvas.height=Math.max(1,Math.round(d.height*(d.dpr||1)));}if(__api){__api.width=d.width;__api.height=d.height;__api.dpr=d.dpr||1;}if(self.Renderer&&typeof self.Renderer.resize==="function")self.Renderer.resize(d.width,d.height,d.dpr||1);return;}',
    'if(d.type==="input"){if(self.Renderer&&typeof self.Renderer.input==="function")self.Renderer.input(d);return;}',
    'if(d.type==="dispose"){if(self.Renderer&&typeof self.Renderer.dispose==="function")self.Renderer.dispose();self.close();return;}',
    '}catch(e){__post({type:"error",message:String(e&&e.message||e)});}};'
  ].join("\n");

  var url = URL.createObjectURL(new Blob(
    [prelude + "\n/* ---- game renderer ---- */\n" + cfg.renderer],
    { type: "text/javascript" }));
  try {
    worker = new Worker(url);
  } catch (e) {
    fail("Worker 创建失败：" + e);
    return;
  } finally {
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }
  // 初始化看门狗：渲染器在加载/init 阶段阻塞（死循环）时也要能终止并降级
  initTimer = setTimeout(function () {
    if (!ready) fail("渲染器初始化超时");
  }, 2500);

  worker.onmessage = function (ev) {
    var d = ev.data || {};
    if (d.type === "ack") { delete pending[d.seq]; return; }
    if (d.type === "ready") {
      ready = true;
      clearTimeout(initTimer);
      hasInput = !!d.hasInput;
      toHost({ type: "ready", hasInput: hasInput });
      return;
    }
    if (d.type === "sfx") { toHost({ type: "sfx", name: d.name }); return; }
    if (d.type === "cell") { toHost({ type: "cell", x: d.x, y: d.y }); return; }
    if (d.type === "error") { fail(d.message); return; }
  };
  worker.onerror = function (ev) { fail((ev && ev.message) || "worker error"); };

  function applySize(w, h, dpr) {
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    if (worker && !dead) worker.postMessage({ type: "resize",
      width: w, height: h, dpr: dpr || 1 });
  }
  function post(msg, transfer) {
    if (worker && !dead) worker.postMessage(msg, transfer || []);
  }

  self.addEventListener("message", function (ev) {
    if (ev.source !== parent) return;
    var d = ev.data || {};
    if (d.type === "state") { post({ type: "state", state: d.state }); return; }
    if (d.type === "tick") {
      if (dead) return;
      seq += 1;
      pending[seq] = performance.now();
      var now = performance.now(), oldest = 0, count = 0;
      for (var k in pending) { count += 1; oldest = Math.max(oldest, now - pending[k]); }
      if (count > 3 || oldest > 200) { fail("渲染器无响应（超时）"); return; }
      post({ type: "tick", t: d.t, dt: d.dt, seq: seq });
      return;
    }
    if (d.type === "resize") { applySize(d.width, d.height, d.dpr); return; }
    if (d.type === "dispose") { post({ type: "dispose" }); dead = true; return; }
  });

  function cellAt(ev) {
    var r = canvas.getBoundingClientRect();
    var x = (ev.clientX - r.left) / Math.max(1, r.width);
    var y = (ev.clientY - r.top) / Math.max(1, r.height);
    return { x: x * cfg.board.w, y: y * cfg.board.h };
  }
  function sendInput(ev, phase) {
    var c = cellAt(ev);
    var cx = Math.floor(c.x), cy = Math.floor(c.y);
    if (cx < 0 || cy < 0 || cx >= cfg.board.w || cy >= cfg.board.h) return null;
    post({ type: "input", x: c.x, y: c.y, cellX: cx, cellY: cy, phase: phase,
           button: ev.button || 0 });
    return { x: cx, y: cy };
  }
  canvas.addEventListener("pointerdown", function (ev) {
    try { canvas.setPointerCapture(ev.pointerId); } catch (e) {}
    sendInput(ev, "down");
  });
  canvas.addEventListener("pointermove", function (ev) { if (ev.buttons) sendInput(ev, "move"); });
  canvas.addEventListener("pointerup", function (ev) {
    var cell = sendInput(ev, "up");
    if (cell && !hasInput) toHost({ type: "cell", x: cell.x, y: cell.y });
  });
  canvas.addEventListener("contextmenu", function (ev) { ev.preventDefault(); });

  // OffscreenCanvas 必须转移（transfer list）给 Worker，且只能转移一次
  post({ type: "init", canvas: offscreen, width: cfg.width, height: cfg.height,
         dpr: cfg.dpr || 1, assets: cfg.assets, board: cfg.board }, [offscreen]);
  applySize(cfg.width, cfg.height, cfg.dpr || 1);
})();
"""

FRAME_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>ugc-renderer</title>
<style>
  html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; }
  #ugc-board { display: block; width: 100%; height: 100%; touch-action: none; }
</style>
</head>
<body>
<canvas id="ugc-board"></canvas>
<script id="ugc-render-cfg" type="application/json">__CFG__</script>
<script>__BOOTSTRAP__</script>
</body>
</html>
"""


def frame_html(version: dict) -> str:
    """构造沙箱帧文档：内联渲染器 + 资源 base64 + 引导脚本。"""
    stored = version["meta"]
    meta = stored.get("meta", stored)
    rend = meta["renderer"]
    root = Path(version["package_path"])
    try:
        source = (root / rend["entry"]).read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(410, "渲染器文件缺失")
    assets = {}
    for name, spec in (meta.get("assets") or {}).items():
        try:
            data = (root / spec["file"]).read_bytes()
            kind, w, h = ugc_pack._sniff_image(spec["file"], data)
        except (OSError, ugc_pack.UGCError):
            continue
        assets[name] = {
            "type": "image/png" if kind == "png" else "image/webp",
            "w": w, "h": h,
            "data": base64.b64encode(data).decode("ascii"),
        }
    cfg = {
        "v": 1,
        "board": {"w": int(meta["board"]["width"]),
                  "h": int(meta["board"]["height"])},
        "width": 320, "height": 320, "dpr": 1,
        "assets": assets,
        "sounds": sorted((meta.get("sounds") or {}).keys()),
        "renderer": source,
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    return (FRAME_HTML.replace("__CFG__", cfg_json)
            .replace("__BOOTSTRAP__", BOOTSTRAP))
