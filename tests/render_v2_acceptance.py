"""渲染 v2 真实浏览器验收（设计 16）：L1 声明式 / L2 资源 / L3 沙箱 + 看门狗降级。

前置：一个已启动并完成播种的后端（官方种子包），以及 ADMIN_USERNAME/ADMIN_PASSWORD。
用法：
  .venv/bin/python tests/render_v2_acceptance.py --base-url http://127.0.0.1:18089

脚本会：注册作者 → 上传 sokoban 示例（含 renderer.js）→ 管理员审核并开启渲染器 →
真实浏览器验证 L1（canvas/HUD/精灵）、L3（opaque-origin iframe 绘制、读不到宿主）与
降级（死循环渲染器 → 看门狗终止 → 声明式渲染接管）。全部使用临时账号与临时游戏。
"""
import argparse
import io
import json
import secrets
import sys
import uuid
import zipfile
import zlib
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SOKOBAN = ROOT / "gdk-ug" / "examples" / "sokoban"
BLOCKING = "while (true) { /* 故意阻塞，验证看门狗 */ }"


def _png_colors(path: Path, max_pixels: int = 200000) -> tuple:
    """极简 PNG 解码（8bit RGB/RGBA、非隔行）：返回 (w, h, 颜色数)。

    只用于验收断言「画面不是空白」，不引入 Pillow 依赖。
    """
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
    pos, w, h, ct, bd, idat = 8, 0, 0, 0, 0, b""
    while pos + 8 <= len(data):
        ln = int.from_bytes(data[pos:pos + 4], "big")
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w = int.from_bytes(chunk[0:4], "big")
            h = int.from_bytes(chunk[4:8], "big")
            bd, ct = chunk[8], chunk[9]
            assert bd == 8 and ct in (2, 6), f"不支持的 PNG 格式 {bd}/{ct}"
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    raw = zlib.decompress(idat)
    bpp = 3 if ct == 2 else 4
    stride = w * bpp
    prev = bytearray(stride)
    colors = set()
    off = 0
    step = max(1, (w * h) // max_pixels)
    for _y in range(h):
        f = raw[off]
        off += 1
        line = bytearray(raw[off:off + stride])
        off += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        for i in range(0, stride, bpp * step):
            colors.add(bytes(line[i:i + 3]))
        prev = line
    return w, h, len(colors)


def _http(method: str, url: str, **kw):
    """直连后端：忽略环境里的代理配置（验收环境可能有非法代理变量）。"""
    with httpx.Client(trust_env=False, timeout=30) as client:
        return client.request(method, url, **kw)


def _zip_pack(files) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _sokoban_pack(slug: str, renderer: str | None) -> bytes:
    files = {}
    for p in sorted(SOKOBAN.rglob("*")):
        if p.is_dir() or "__pycache__" in p.parts:
            continue
        if p.name == "renderer.js" and renderer is not None:
            continue
        files[p.relative_to(SOKOBAN).as_posix()] = p.read_bytes()
    yaml = files["game.yaml"].decode("utf-8").replace("slug: sokoban", f"slug: {slug}")
    files["game.yaml"] = yaml.encode("utf-8")
    if renderer is not None:
        files["renderer.js"] = renderer.encode("utf-8")
    return _zip_pack(files)


def _register(base: str, prefix: str) -> dict:
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    r = _http("POST", base + "/api/v1/auth/register",
              json={"username": username, "password": secrets.token_urlsafe(18)})
    r.raise_for_status()
    return r.json()


def _auth(user: dict) -> dict:
    return {"Authorization": f"Bearer {user['token']}"}


def _upload(base: str, user: dict, data: bytes, slug: str) -> int:
    r = _http("POST", base + "/api/v1/ugc/games", headers=_auth(user),
              files={"file": (f"{slug}.zip", data, "application/zip")},
              data={"changelog": "render-v2 acceptance"})
    r.raise_for_status()
    return r.json()["game"]["id"]


def _publish(base: str, user: dict, admin: dict, gid: int):
    r = _http("POST", f"{base}/api/v1/ugc/games/{gid}/submit", headers=_auth(user))
    r.raise_for_status()
    r = _http("POST", f"{base}/api/v1/admin/ugc/{gid}/approve", headers=_auth(admin))
    r.raise_for_status()


def _enable_renderer(base: str, admin: dict, gid: int, enabled: bool = True):
    r = _http("POST", f"{base}/api/v1/admin/ugc/{gid}/renderer",
              headers=_auth(admin), json={"enabled": enabled})
    r.raise_for_status()


def run(base_url: str, output: Path) -> dict:
    import os
    admin_name = os.environ.get("ADMIN_USERNAME")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    if not admin_name or not admin_pass:
        raise SystemExit("需要 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量")
    output.mkdir(parents=True, exist_ok=True)

    r = _http("POST", base_url + "/api/v1/auth/login",
              json={"username": admin_name, "password": admin_pass})
    r.raise_for_status()
    admin = r.json()
    author = _register(base_url, "renderv2")

    suffix = uuid.uuid4().hex[:6]
    slug_ok = f"soko-{suffix}"
    slug_bad = f"soko-loop-{suffix}"
    gid_ok = _upload(base_url, author, _sokoban_pack(slug_ok, None), slug_ok)
    gid_bad = _upload(base_url, author, _sokoban_pack(slug_bad, BLOCKING), slug_bad)
    _publish(base_url, author, admin, gid_ok)     # 先发布但不开启渲染器
    _publish(base_url, author, admin, gid_bad)

    result = {"base_url": base_url, "game_ok": slug_ok, "game_bad": slug_bad,
              "checks": {}, "page_errors": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # 登录态注入（游玩会话需要登录）：先访问同源，再写入 gp_token/gp_user
        page.goto(base_url + "/")
        page.evaluate(
            "([t, u]) => { localStorage.setItem('gp_token', t);"
            " localStorage.setItem('gp_user', JSON.stringify(u)); }",
            [author["token"], author.get("user") or {}])

        # --- L1：官方包声明式渲染（canvas + HUD + 精灵） ---
        page.goto(base_url + "/games/snake")
        expect(page.locator("canvas").first).to_be_visible()
        expect(page.get_by_text("分数", exact=True).first).to_be_visible()
        expect(page.get_by_text("TICK", exact=False).first).to_be_visible()
        page.screenshot(path=str(output / "snake-l1.png"), full_page=True)
        result["checks"]["snake_canvas_hud"] = True

        page.goto(base_url + "/games/tetris")
        expect(page.locator("canvas").first).to_be_visible()
        expect(page.get_by_text("NEXT", exact=True).first).to_be_visible()
        page.screenshot(path=str(output / "tetris-l1.png"), full_page=True)
        result["checks"]["tetris_next_miniboard"] = True

        page.goto(base_url + "/games/microrts")
        expect(page.locator("canvas").first).to_be_visible()
        expect(page.get_by_text("金矿 P0", exact=False).first).to_be_visible()
        page.screenshot(path=str(output / "microrts-l1.png"), full_page=True)
        result["checks"]["microrts_owner_hud"] = True

        # --- L3 门禁：已发布但未开启渲染器 → 无 iframe ---
        page.goto(base_url + f"/games/{slug_ok}")
        expect(page.locator("canvas").first).to_be_visible()
        assert page.locator("iframe").count() == 0, "未开启渲染器却出现了 iframe"
        result["checks"]["renderer_gated_off"] = True

        # --- 开启后：opaque-origin iframe 真正绘制 ---
        _enable_renderer(base_url, admin, gid_ok)
        page.goto(base_url + f"/games/{slug_ok}")
        frame_el = page.locator("iframe")
        expect(frame_el.first).to_be_visible()
        assert frame_el.first.get_attribute("sandbox") == "allow-scripts"
        frame = next((f for f in page.frames if "/render/" in f.url), None)
        assert frame is not None, "找不到沙箱帧"
        blocked = frame.evaluate(
            "(() => { try { return window.parent.document.title } catch (e) { return 'blocked' } })()")
        assert blocked == "blocked", f"沙箱帧能读宿主 DOM：{blocked}"
        expect(frame.locator("canvas#ugc-board")).to_have_count(1)
        shot = output / "sandbox-frame.png"
        frame_el.first.screenshot(path=str(shot))
        sw, sh, colors = _png_colors(shot)
        assert sw > 40 and sh > 40 and colors >= 4, \
            f"沙箱帧画面疑似空白：{sw}x{sh} colors={colors}"
        page.screenshot(path=str(output / "sandbox-page.png"), full_page=True)
        result["checks"]["sandbox_draws_and_isolated"] = True

        # --- 看门狗：死循环渲染器 → 终止 + 声明式接管 ---
        _enable_renderer(base_url, admin, gid_bad)
        page.goto(base_url + f"/games/{slug_bad}")
        page.wait_for_selector("iframe", state="detached", timeout=15000)
        expect(page.locator("canvas").first).to_be_visible()
        fail_key = f"ugc-renderer-fail:{slug_bad}:1.0.0"
        assert page.evaluate(f"sessionStorage.getItem('{fail_key}')") == "1"
        page.screenshot(path=str(output / "sandbox-fallback.png"), full_page=True)
        result["checks"]["watchdog_fallback"] = True

        result["page_errors"] = errors
        context.close()
        browser.close()

    assert not result["page_errors"], result["page_errors"]
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path,
                        default=Path("/tmp/gameplatform-render-v2"))
    args = parser.parse_args()
    print(json.dumps(run(args.base_url.rstrip("/"), args.output),
                     ensure_ascii=False, indent=2))
    sys.exit(0)
