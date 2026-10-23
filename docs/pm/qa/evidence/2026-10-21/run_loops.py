import json, os, sys, time, pathlib
import requests

API = "http://127.0.0.1:8080"
OUT = pathlib.Path("/tmp/loopwalk"); OUT.mkdir(exist_ok=True)
log = {"api": API, "started": time.time(), "steps": []}

def rec(usecase, step, ok, detail):
    entry = {"usecase": usecase, "step": step, "ok": ok, "detail": detail}
    log["steps"].append(entry)
    print(("PASS" if ok else "FAIL"), usecase, "|", step, "|", detail)
    return entry

def auth(user, pw, register=True):
    r = requests.post(API + "/api/v1/auth/login", json={"username": user, "password": pw})
    if r.status_code != 200 and register:
        r = requests.post(API + "/api/v1/auth/register", json={"username": user, "password": pw})
    r.raise_for_status()
    return r.json()["token"]

def h(tok):
    return {"Authorization": "Bearer " + tok}

def get(path, tok=None):
    return requests.get(API + path, headers=h(tok) if tok else {})

def post(path, body=None, tok=None):
    return requests.post(API + path, json=body, headers=h(tok) if tok else {})

u1 = auth("loopuser", "<test-password>")
u2 = auth("loopuser2", "<test-password>")
rec("setup", "users", True, "loopuser / loopuser2 logged in")

# ---------- U06 P3 training loop (repo ONNX fixture upload chain) ----------
r = get("/api/ready"); rec("U06", "1 API ready", r.status_code == 200, r.text[:120])
r = get("/api/games"); games = [g.get("id") for g in r.json().get("games", [])] if r.status_code == 200 else []
rec("U06", "1 games", r.status_code == 200 and "snake" in games, str(games))
r = get("/api/openenv/list_environments"); rec("U06", "2 openenv list", r.status_code == 200, r.text[:160])

fixture = "/home/leoric/code/gameplatform/docs/pm/qa/fixtures/snake-rotwin-min.onnx"
files = {"file": ("snake-rotwin-min.onnx", open(fixture, "rb"), "application/octet-stream")}
r = requests.post(API + "/api/v1/models", files=files, data={"game": "snake", "name": "loop-snake-min"}, headers=h(u1))
upload = r.json() if r.status_code == 200 else {}
model = upload.get("model") or {}
mid = model.get("id")
rec("U06", "3 upload fixture ONNX", r.status_code == 200 and bool(mid), f"status={r.status_code} model={json.dumps({k:model.get(k) for k in ('id','name','game','io_contract','status')}, ensure_ascii=False)}")

r = get("/api/v1/models", u1); lst = r.json().get("models", [])
rec("U06", "3 model listed", any(m.get("id") == mid for m in lst), f"{len(lst)} models")

r = post(f"/api/v1/models/{mid}/eval", {}, u1)
metrics = (r.json() or {}).get("metrics") if r.status_code == 200 else None
rec("U06", "4 eval", r.status_code == 200, f"status={r.status_code} metrics={json.dumps(metrics, ensure_ascii=False)}")

r = get(f"/api/v1/models/{mid}", u1); meta = (r.json().get("model") or {}).get("meta")
rec("U06", "5 eval persisted", bool(meta and meta.get("eval")), f"meta={json.dumps(meta, ensure_ascii=False)[:200]}")

if mid:
    r = post("/api/v1/matches", {"game": "snake", "model_a": mid, "model_b": "ai:dqn"}, u1)
    rec("U06", "6 model challenge (snake vs ai:dqn)", r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")
    r = post("/api/v1/matches", {"game": "snake", "model_a": mid, "model_b": mid}, u1)
    rec("U06", "6 model vs model (snake)", r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")

# ---------- U11 PvE play loop (snake) ----------
r = post("/api/v1/snake/play/sessions", {"kind": "pve", "seed": 42}, u1)
sess = (r.json() or {}).get("session") or {}
sid = sess.get("id")
rec("U11", "1 create pve session", r.status_code == 200 and bool(sid), f"sid={sid} status={sess.get('status')} tick={sess.get('tick')}")
if sid:
    done = False; tick = 0; match_id = None; steps = 0
    while not done and steps < 400:
        steps += 1
        r = post(f"/api/v1/snake/play/sessions/{sid}/actions", {"actions": 1}, u1)
        if r.status_code != 200:
            rec("U11", "2 actions", False, f"status={r.status_code} body={r.text[:160]}")
            break
        d = r.json(); done = bool(d.get("done")); tick = d.get("tick", tick); match_id = d.get("match_id") or match_id
    rec("U11", "2 actions->finish", done, f"steps={steps} tick={tick} match_id={match_id}")
    r = get(f"/api/v1/snake/play/sessions/{sid}"); rec("U11", "3 session finished", r.status_code == 200 and r.json().get("session", {}).get("status") == "finished", r.text[:160])
    if match_id:
        r = post("/api/snake/scores", {"match_id": match_id, "name": "loopuser"}, u1)
        rec("U11", "4 submit score", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    r = get("/api/snake/scores"); rec("U11", "5 leaderboard", r.status_code == 200 and bool(r.json().get("items")), r.text[:200])
    r = post("/api/v1/snake/play/sessions", {"kind": "pve", "seed": 43}, u1)
    rec("U11", "6 replay/again (new session)", r.status_code == 200, (r.text[:120]))

# ---------- U13 PvP room loop (microrts, ranked) ----------
r = post("/api/v1/microrts/play/sessions", {"kind": "pvp", "mode": "ranked", "visibility": "public"}, u1)
room = (r.json() or {}); rs = room.get("session") or {}; rsid = rs.get("id"); invite = room.get("invite")
rec("U13", "1 create room", r.status_code == 200 and bool(rsid), f"sid={rsid} invite={invite} status={rs.get('status')}")
if rsid and invite:
    r = post("/api/v1/microrts/play/sessions", {"kind": "pvp", "invite": invite}, u2)
    rec("U13", "2 join by invite", r.status_code == 200 and (r.json().get("session") or {}).get("status") == "active", f"status={r.status_code} body={r.text[:140]}")
    r = get("/api/v1/play/active", u1); actives = (r.json() or {}).get("sessions", [])
    rec("U13/U15", "3 active session visible", any(s.get("id") == rsid for s in actives), f"active={[s.get('id') for s in actives]}")
    for i in range(3):
        r1 = post(f"/api/v1/microrts/play/sessions/{rsid}/actions", {"actions": []}, u1)
        r2 = post(f"/api/v1/microrts/play/sessions/{rsid}/actions", {"actions": []}, u2)
        rec("U13", f"4 tick {i+1}", r1.status_code == 200 and r2.status_code == 200, f"p0={r1.status_code} p1={r2.status_code}")
        if (r1.json() or {}).get("done"):
            break
    r = post(f"/api/v1/microrts/play/sessions/{rsid}/leave", {}, u1)
    rec("U13", "5 resign p0", r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")
    r = get(f"/api/v1/microrts/play/sessions/{rsid}")
    rec("U13", "6 finished", r.status_code == 200 and (r.json().get("session") or {}).get("status") == "finished", f"body={r.text[:200]}")
    r = get("/api/v1/leaderboards/microrts?scope=total", u1); rec("U13", "7 leaderboard", r.status_code == 200, r.text[:200])
    r = get("/api/v1/ratings/microrts", u1); rec("U13", "8 ratings", r.status_code == 200, r.text[:200])
    r = post(f"/api/v1/microrts/play/sessions/{rsid}/rematch", {}, u1)
    rec("U13", "9 rematch", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        newid = (r.json().get("session") or {}).get("id")
        requests.post(API + f"/api/v1/microrts/play/sessions/{newid}/leave", json={}, headers=h(u1))

log["finished"] = time.time()
(OUT / "run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2))
fails = [s for s in log["steps"] if not s["ok"]]
print(f"\nTOTAL {len(log['steps'])} steps, FAIL {len(fails)}")
