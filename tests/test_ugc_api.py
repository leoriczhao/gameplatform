"""UGC API tests (11 P3): upload → draft → submit → approve/publish →
registry integration; reject/unpublish/ban; quotas; static scan; author ban."""
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
import registry  # noqa: E402
import ugc  # noqa: E402
from openenv_helpers import ws_message, ws_reset, ws_step  # noqa: E402

client = TestClient(main.app)

GOOD_YAML = """slug: counter
title: 计数器
description: 测试用计数器
version: 1.0.0
board:
  width: 4
  height: 4
  palette:
    empty: { glyph: "·" }
    full:  { glyph: "■" }
"""

COUNTER_CODE = '''
class Counter:
    score_bounds = (0, 100)
    def info(self):
        return {"grid": [4, 4], "action_space": "0-1"}
    def new_state(self, seed, options=None):
        return {"tick": 0, "done": False, "winner": None, "cause": None,
                "n": 0, "board": [["empty"] * 4 for _ in range(4)]}
    def validate_state(self, state):
        if state["board"][0][0] not in ("empty", "full"):
            raise ValueError("bad cell")
    def validate_action(self, action, state):
        if not isinstance(action, int):
            raise ValueError("int required")
    def step_state(self, state, action):
        if state.get("done"):
            return state
        s = dict(state, n=state["n"] + 1, tick=state["tick"] + 1)
        s["board"] = [row[:] for row in state["board"]]
        s["board"][0][0] = "full" if s["n"] >= 10 else "empty"
        if s["n"] >= 10:
            s.update(done=True, winner=0, cause="done")
        return s
    def sample_action(self, state):
        return 1
def get_adapter():
    return Counter()
'''


def _user(name):
    r = client.post("/api/v1/auth/register",
                    json={"username": name, "password": "password123"})
    assert r.status_code == 200, r.text
    return r.json()


def _h(u):
    return {"Authorization": f"Bearer {u['token']}"}


def _pack(slug: str, code: str = COUNTER_CODE, version: str = "1.0.0") -> bytes:
    yaml = GOOD_YAML.replace("slug: counter", f"slug: {slug}")
    if version != "1.0.0":
        yaml = yaml.replace("version: 1.0.0", f"version: {version}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("game.yaml", yaml)
        zf.writestr("__init__.py", code)
        zf.writestr("README.md", "# 玩法\n")
    return buf.getvalue()


def _upload(user, slug, code=COUNTER_CODE, version="1.0.0"):
    data = _pack(slug, code, version)
    return client.post("/api/v1/ugc/games",
                       files={"file": (f"{slug}.zip", data, "application/zip")},
                       data={"changelog": "init"}, headers=_h(user))


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "ugcadmin1")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminsecret1")
    admin_store.bootstrap_admin()
    r = client.post("/api/v1/auth/login",
                    json={"username": "ugcadmin1",
                          "password": "adminsecret1"})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_requires_login():
    data = _pack("anon-x")
    r = client.post("/api/v1/ugc/games",
                    files={"file": ("x.zip", data, "application/zip")})
    assert r.status_code == 401


def test_upload_draft_visibility():
    A = _user("uqca1")
    r = _upload(A, "counter-a1")
    assert r.status_code == 200, r.text
    assert r.json()["game"]["status"] == "draft"
    assert r.json()["version"]["meta"]["smoke"]["ok"] is True
    mine = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"]
    assert any(g["slug"] == "counter-a1" for g in mine)
    pub = client.get("/api/v1/ugc/games?status=published").json()["games"]
    assert all(g["slug"] != "counter-a1" for g in pub)


def test_submit_approve_publish_full_integration(admin):
    A = _user("uqca2")
    assert _upload(A, "counter-a2").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    # 提交审核：进入队列，仍不在公开目录
    r = client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    assert r.status_code == 200 and r.json()["game"]["status"] == "pending"
    # 提交后仍不在公开目录（目录里可能有其他已公开游戏，如种子游戏）
    pub0 = client.get("/api/v1/ugc/games?status=published").json()["games"]
    assert all(g["slug"] != "counter-a2" for g in pub0)
    queue = client.get("/api/v1/admin/ugc", headers=_h(admin)).json()["games"]
    assert any(g["id"] == gid for g in queue)
    # 通过 → 公开 + 注册表 + /api/games + 官方 OpenEnv WS 全通
    r = client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert r.status_code == 200, r.text
    assert r.json()["game"]["status"] == "published"
    pub = client.get("/api/v1/ugc/games?status=published").json()["games"]
    assert any(g["slug"] == "counter-a2" for g in pub)
    catalog = client.get("/api/games").json()["games"]
    assert any(g["id"] == "counter-a2" for g in catalog)
    assert "counter-a2" in registry.GAMES
    with client.websocket_connect("/api/openenv/counter-a2/ws") as ws:
        result = ws_reset(ws, seed=1, obs_mode="state")
        assert len(result["observation"]["state"]["board"]) == 4
        assert ws_step(ws, 1)["observation"]["state"]["tick"] == 1


def test_reject_flow(admin):
    A = _user("uqca3")
    assert _upload(A, "counter-a3").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    r = client.post(f"/api/v1/admin/ugc/{gid}/reject",
                    json={"note": "玩法太简单"}, headers=_h(admin))
    assert r.status_code == 200
    assert r.json()["game"]["status"] == "draft"
    mine = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"]
    assert mine[0]["review_note"] == "玩法太简单"


def test_author_unpublish(admin):
    A = _user("uqca4")
    assert _upload(A, "counter-a4").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert "counter-a4" in registry.GAMES
    with client.websocket_connect("/api/openenv/counter-a4/ws") as ws:
        ws_reset(ws, seed=1, obs_mode="state")
        r = client.post(f"/api/v1/ugc/games/{gid}/unpublish", headers=_h(A))
        assert r.status_code == 200 and r.json()["game"]["status"] == "draft"
        assert "counter-a4" not in registry.GAMES
        error = ws_message(ws, "step", {"value": 1})
        assert error["type"] == "error", error
    assert client.get("/api/openenv/counter-a4/schema").status_code == 404


def test_admin_ban_and_permissions(admin):
    A = _user("uqca5")
    B = _user("uqcb5")
    assert _upload(A, "counter-a5").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    # 非 admin 调管理面 403；游客 401
    assert client.get("/api/v1/admin/ugc", headers=_h(B)).status_code == 403
    assert client.get("/api/v1/admin/ugc").status_code == 401
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    # ban → 玩家 404；unban → 回到 draft
    r = client.post(f"/api/v1/admin/ugc/{gid}/ban", headers=_h(admin))
    assert r.status_code == 200 and r.json()["game"]["status"] == "banned"
    assert "counter-a5" not in registry.GAMES
    client.post(f"/api/v1/admin/ugc/{gid}/unban", headers=_h(admin))
    assert client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["status"] == "draft"


def test_quota_limits():
    A = _user("uqca6")
    for i in range(5):
        r = _upload(A, f"counter-a6-{i}")
        assert r.status_code == 200, r.text
    r = _upload(A, "counter-a6-extra")
    assert r.status_code == 400 and "上限" in r.text


def test_version_increment_and_swap(admin):
    A = _user("uqca7")
    assert _upload(A, "counter-a7", version="1.0.0").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    # 相同版本号拒绝；更高版本通过
    data = _pack("counter-a7", version="1.0.0")
    r = client.post(f"/api/v1/ugc/games/{gid}/versions",
                    files={"file": ("v.zip", data, "application/zip")},
                    data={"changelog": "noop"}, headers=_h(A))
    assert r.status_code == 400
    data = _pack("counter-a7", version="2.0.0")
    r = client.post(f"/api/v1/ugc/games/{gid}/versions",
                    files={"file": ("v2.zip", data, "application/zip")},
                    data={"changelog": "更快"}, headers=_h(A))
    assert r.status_code == 200, r.text
    # 审核期旧版本继续服务
    with client.websocket_connect("/api/openenv/counter-a7/ws") as ws:
        result = ws_reset(ws, seed=1, obs_mode="state")
        assert result["observation"]["metadata"]["environment"]["version"] == "1.0.0"
        assert ws_step(ws, 1)["observation"]["state"]["tick"] == 1
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    pub = client.get("/api/v1/ugc/games?status=published").json()["games"]
    mine = [g for g in pub if g["slug"] == "counter-a7"]
    assert mine and mine[0]["version"] == "2.0.0"


def test_static_scan_rejects_bad_imports():
    A = _user("uqca8")
    bad = "import socket\n" + COUNTER_CODE
    r = _upload(A, "counter-a8", code=bad)
    assert r.status_code == 400
    assert "静态扫描" in r.text


def test_ban_author_takes_down_games(admin):
    A = _user("uqca9")
    assert _upload(A, "counter-a9").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert "counter-a9" in registry.GAMES
    # 封禁作者 → 游戏下架（env 404、公开目录消失）
    r = client.post(f"/api/v1/admin/users/{A['user']['id']}/status",
                    json={"status": "banned"}, headers=_h(admin))
    assert r.status_code == 200, r.text
    assert "counter-a9" not in registry.GAMES
    pub = client.get("/api/v1/ugc/games?status=published").json()["games"]
    assert all(g["slug"] != "counter-a9" for g in pub)
    # 解封作者（清理，避免影响后续）
    client.post(f"/api/v1/admin/users/{A['user']['id']}/status",
                json={"status": "active"}, headers=_h(admin))


def test_fuse_pause_and_resume(admin):
    A = _user("uqca11")
    assert _upload(A, "counter-a11").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    assert "counter-a11" in registry.GAMES
    # 熔断（worker 连续失败回调）→ paused + 下架
    ugc.fuse(gid)
    g = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]
    assert g["status"] == "paused"
    assert "counter-a11" not in registry.GAMES
    # admin resume → published + 回注册表
    r = client.post(f"/api/v1/admin/ugc/{gid}/resume", headers=_h(admin))
    assert r.status_code == 200 and r.json()["game"]["status"] == "published"
    assert "counter-a11" in registry.GAMES


def test_delete_draft_only(admin):
    A = _user("uqca10")
    assert _upload(A, "counter-a10").status_code == 200
    gid = client.get("/api/v1/ugc/games", headers=_h(A)).json()["games"][0]["id"]
    client.post(f"/api/v1/ugc/games/{gid}/submit", headers=_h(A))
    client.post(f"/api/v1/admin/ugc/{gid}/approve", headers=_h(admin))
    r = client.delete(f"/api/v1/ugc/games/{gid}", headers=_h(A))
    assert r.status_code == 400 and "草稿" in r.text
    client.post(f"/api/v1/ugc/games/{gid}/unpublish", headers=_h(A))
    r = client.delete(f"/api/v1/ugc/games/{gid}", headers=_h(A))
    assert r.status_code == 200
