/* 推箱子沙箱渲染器示例（docs/design/16 §5.3）。
   API: init(api) / resize(w,h,dpr) / frame(state, t, dt)
   api = { ctx, width, height, dpr, sprite(name), sfx(name), cell(x, y), sprites }
   规则：只读 state、只画 2D canvas；不得访问 DOM/网络/存储（会被静态扫描拒绝）。 */
(function () {
  "use strict";
  var ctx = null, W = 1, H = 1, DPR = 1;

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function draw(state, t) {
    if (!ctx || !state || !state.board) return;
    var grid = state.board;
    var rows = grid.length, cols = grid[0] ? grid[0].length : 0;
    if (!rows || !cols) return;
    var cw = W / cols, ch = H / rows;

    ctx.save();
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);

    for (var y = 0; y < rows; y += 1) {
      for (var x = 0; x < cols; x += 1) {
        var cell = String(grid[y][x]);
        var px = x * cw, py = y * ch;
        ctx.fillStyle = (x + y) % 2 ? "#eef2f7" : "#f8fafc";
        ctx.fillRect(px, py, cw, ch);
        if (cell === "wall") {
          ctx.fillStyle = "#94a3b8";
          roundRect(px + cw * 0.08, py + ch * 0.08, cw * 0.84, ch * 0.84, cw * 0.18);
          ctx.fill();
        } else if (cell === "target") {
          ctx.strokeStyle = "#f59e0b";
          ctx.lineWidth = Math.max(2, cw * 0.08);
          ctx.beginPath();
          ctx.arc(px + cw / 2, py + ch / 2, Math.min(cw, ch) * 0.2, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }

    var units = state.units || [];
    for (var i = 0; i < units.length; i += 1) {
      var u = units[i], ux = u.x * cw, uy = u.y * ch;
      if (u.type === "box") {
        ctx.fillStyle = "#b45309";
        roundRect(ux + cw * 0.12, uy + ch * 0.12, cw * 0.76, ch * 0.76, cw * 0.12);
        ctx.fill();
        ctx.strokeStyle = "#fbbf24";
        ctx.lineWidth = Math.max(1, cw * 0.05);
        ctx.stroke();
      } else {
        ctx.fillStyle = "#4f46e5";
        ctx.beginPath();
        ctx.arc(ux + cw / 2, uy + ch / 2, Math.min(cw, ch) * 0.32, 0, Math.PI * 2);
        ctx.fill();
        var look = Math.sin((t || 0) / 600) * cw * 0.05;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(ux + cw * 0.4 + look, uy + ch * 0.42, cw * 0.07, 0, Math.PI * 2);
        ctx.arc(ux + cw * 0.6 + look, uy + ch * 0.42, cw * 0.07, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }

  globalThis.Renderer = {
    init: function (api) {
      ctx = api.ctx; W = api.width; H = api.height; DPR = api.dpr || 1;
    },
    resize: function (w, h, dpr) { W = w; H = h; DPR = dpr || 1; },
    frame: function (state, t) { draw(state, t); },
  };
})();
