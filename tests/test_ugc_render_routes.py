"""渲染 v2 资源/帧路由测试（设计 16 §4.2/§5）：白名单、嗅探、门禁、CSP。"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")
os.environ["MODELS_DIR"] = str(Path(_tmp.name) / "models")

from fastapi.testclient import TestClient  # noqa: E402

import admin as admin_store  # noqa: E402
import main  # noqa: E402
import ugc  # noqa: E402

client = TestClient(main.app)

RENDER_YAML = """slug: render-x
title: 渲染测试
description: 带资源与沙箱渲染器
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
    full:  { sprite: dot }
assets:
  dot: { file: "assets/dot.png" }
renderer:
  entry: renderer.js
"""

CODE = '''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1"}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "n": 0, "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        pass
    def validate_action(self, action, state):
        if not isinstance(action, int):
            raise ValueError("int required")
    def step_state(self, state, action):
        return dict(state, tick=state["tick"] + 1, n=state["n"] + 1)
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''

RENDERER_JS = ("globalThis.Renderer = { frame(state) { const c = this.ctx;"
               " } };\n")


def _png(w=2, h=3) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
            + w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00" + b"\x00" * 8)


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


@pytest.fixture(scope="module")
def admin():
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": os.environ.get("ADMIN_USERNAME", "seedadmin"),
                          "password": os.environ.get("ADMIN_PASSWORD", "adminsecret1")})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def published(admin):
    A = _user("rendera1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", RENDER_YAML)
        zf.writestr("__init__.py", CODE)
        zf.writestr("assets/dot.png", _png())
        zf.writestr("renderer.js", RENDERER_JS)
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("r.zip", buf.getvalue(), "application/zip")},
                    data={"changelog": "init"}, headers=_h(A))
    assert r.status_code == 200, r.text
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    r = client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert r.status_code == 200, r.text
    return {"author": A, "gid": gid, "admin": admin}


def test_asset_requires_declaration_and_auth(published):
    A = published["author"]
    base = "/api/ugc/assets/render-x/1.0.0/"
    # 作者草稿可读自己的资源
    r = client.get(base + "assets/dot.png", headers=_h(A))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in r.headers["cache-control"]
    assert r.content == _png()
    # 匿名与未声明路径
    assert client.get(base + "assets/dot.png").status_code == 200  # 已公开
    assert client.get(base + "assets/other.png").status_code == 404
    assert client.get(base + "game.yaml").status_code == 404
    assert client.get(base + "../game.yaml").status_code == 404
    assert client.get("/api/ugc/assets/render-x/9.9.9/assets/dot.png").status_code == 404


def test_frame_is_gated_by_admin_switch(published):
    A, gid = published["author"], published["gid"]
    frame = "/api/ugc/render/render-x/1.0.0/frame"
    # UGC 渲染器默认关闭
    assert client.get(frame).status_code == 403
    assert client.get(f"/api/v1/admin/ugc/{gid}/renderer",
                      headers=_h(A)).status_code == 403
    r = client.get(f"/api/v1/admin/ugc/{gid}/renderer",
                   headers=_h(published["admin"]))
    assert r.status_code == 200
    assert "globalThis.Renderer" in r.json()["renderer"]["source"]
    assert r.json()["enabled"] is False
    # 开启 → 帧可用 + CSP 沙箱头 + 内联渲染器
    r = client.post(f"/api/v1/admin/ugc/{gid}/renderer",
                    json={"enabled": True}, headers=_h(published["admin"]))
    assert r.status_code == 200, r.text
    r = client.get(frame)
    assert r.status_code == 200, r.text
    csp = r.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp and "connect-src 'none'" in csp
    assert "worker-src blob:" in csp
    assert "globalThis.Renderer" in r.text
    assert "ugc-render-cfg" in r.text
    # 公开目录暴露 renderer_enabled
    cat = client.get("/api/games").json()["games"]
    entry = next(g for g in cat if g["id"] == "render-x")
    assert entry["meta"]["renderer_enabled"] is True
    # 关闭 → 403
    client.post(f"/api/v1/admin/ugc/{gid}/renderer",
                json={"enabled": False}, headers=_h(published["admin"]))
    assert client.get(frame).status_code == 403
    # 重新开启，留给后续用例
    client.post(f"/api/v1/admin/ugc/{gid}/renderer",
                json={"enabled": True}, headers=_h(published["admin"]))


def test_renderer_scan_rejects_network_code():
    A = _user("rendererb1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", RENDER_YAML.replace("slug: render-x",
                                                     "slug: render-y"))
        zf.writestr("__init__.py", CODE)
        zf.writestr("assets/dot.png", _png())
        zf.writestr("renderer.js", "fetch('/api/games');")
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("r.zip", buf.getvalue(), "application/zip")},
                    data={"changelog": "init"}, headers=_h(A))
    assert r.status_code == 400, r.text
    assert "渲染器静态扫描" in r.text


def test_frame_escapes_script_close(tmp_path):
    """renderer.js 里的 </script> 必须被转义，不能逃出内联 JSON。"""
    import ugc_assets
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "renderer.js").write_text(
        'globalThis.Renderer = { frame() { const s = "</script>"; } };',
        encoding="utf-8")
    version = {
        "package_path": str(pkg),
        "meta": {"meta": {"board": {"width": 2, "height": 2},
                          "renderer": {"entry": "renderer.js"},
                          "assets": {}}},
    }
    html = ugc_assets.frame_html(version)
    assert "<\\/script>" in html            # 已转义
    assert html.count("<script") == 2        # cfg + bootstrap（未被注入破坏）


def test_admin_can_preview_draft_assets(published):
    """审核需要：管理员能读未发布版本的资源（作者之外）。"""
    B = _user("renderpreview1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", RENDER_YAML.replace("slug: render-x",
                                                     "slug: render-z"))
        zf.writestr("__init__.py", CODE)
        zf.writestr("assets/dot.png", _png())
        zf.writestr("renderer.js", RENDERER_JS)
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("r.zip", buf.getvalue(), "application/zip")},
                    data={"changelog": "init"}, headers=_h(B))
    assert r.status_code == 200, r.text
    url = "/api/ugc/assets/render-z/1.0.0/assets/dot.png"
    assert client.get(url).status_code == 404                     # 匿名
    assert client.get(url, headers=_h(B)).status_code == 200      # 作者
    assert client.get(url, headers=_h(published["admin"])).status_code == 200


def test_frame_transfers_offscreen_canvas():
    """回归：OffscreenCanvas 必须放进 transfer list，否则 Worker 初始化即失败。"""
    import ugc_assets
    assert "worker.postMessage(msg, transfer || [])" in ugc_assets.BOOTSTRAP
    assert "}, [offscreen])" in ugc_assets.BOOTSTRAP
    assert "canvas: offscreen," in ugc_assets.BOOTSTRAP
    assert "渲染器初始化超时" in ugc_assets.BOOTSTRAP   # init 阶段死循环也要能降级


def test_ban_disables_renderer(published):
    gid = published["gid"]
    client.post(f"/api/v1/admin/ugc/{gid}/ban", headers=_h(published["admin"]))
    assert client.get("/api/ugc/render/render-x/1.0.0/frame").status_code == 403
    client.post(f"/api/v1/admin/ugc/{gid}/unban", headers=_h(published["admin"]))
