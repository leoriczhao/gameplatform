import json, os, re, time, zipfile, pathlib, shutil
import requests
API="http://127.0.0.1:8080"
OUT=pathlib.Path("/tmp/loopwalk"); OUT.mkdir(exist_ok=True)
LOG={"steps":[]}
def rec(case,step,ok,detail):
    LOG["steps"].append({"case":case,"step":step,"ok":bool(ok),"detail":str(detail)[:500]})
    print(("PASS" if ok else "FAIL"),case,"|",step,"|",str(detail)[:180])
def login(u,p):
    r=requests.post(API+"/api/v1/auth/login",json={"username":u,"password":p})
    if r.status_code!=200:
        r=requests.post(API+"/api/v1/auth/register",json={"username":u,"password":p})
    r.raise_for_status(); return r.json()
def H(tok): return {"Authorization":"Bearer "+tok}
def get(p,tok=None): return requests.get(API+p,headers=H(tok) if tok else {})
def post(p,b=None,tok=None): return requests.post(API+p,json=b if b is not None else {},headers=H(tok) if tok else {})
def delete(p,tok=None): return requests.delete(API+p,headers=H(tok) if tok else {})

try:
    loop=login("loopuser","<test-password>")
    loop2=login("loopuser2","<test-password>")
    adm=login("labadmin","<test-password>")
    u3=login("verifyuser","<test-password>")
    guest=requests.post(API+"/api/v1/auth/guest").json()
except Exception as e:
    print("setup failed",e); raise

# U01 guest browse
r=get("/api/games"); games=[g.get("id") for g in r.json().get("games",[])] if r.status_code==200 else []
rec("U01","guest games", r.status_code==200 and all(g in games for g in ("snake","tetris","microrts")), f"status={r.status_code} games={games}")
r=get("/api/openenv/list_environments"); rec("U01","guest openenv list", r.status_code==200, r.text[:120])

# U03 public watch + U17 anonymous session
r=post("/api/v1/microrts/play/sessions",{"kind":"pvp","mode":"casual","visibility":"public"},loop["token"])
room=r.json(); rsid=(room.get("session") or {}).get("id"); invite=room.get("invite")
r=get(f"/api/v1/microrts/play/sessions/{rsid}"); rec("U03","guest watch public session", r.status_code==200, f"status={r.status_code}")
if rsid:
    post(f"/api/v1/microrts/play/sessions/{rsid}/leave",{},loop["token"])

# create a real pvp match for replay/anon + ratings
r=post("/api/v1/microrts/play/sessions",{"kind":"pvp","mode":"ranked","visibility":"public"},loop["token"])
room=r.json(); sid=(room.get("session") or {}).get("id"); inv=room.get("invite")
r=post("/api/v1/microrts/play/sessions",{"kind":"pvp","invite":inv},loop2["token"])
post(f"/api/v1/microrts/play/sessions/{sid}/leave",{},loop["token"])
matches=get("/api/v1/matches",loop["token"]).json().get("matches",[])
mid=matches[0]["id"] if matches else None
if mid:
    r=get(f"/api/v1/matches/{mid}/replay"); rec("U03","guest replay", r.status_code==200, f"match={mid} status={r.status_code} moves={len((r.json().get('replay') or {}).get('moves') or [])}")
else:
    rec("U03","guest replay", False, "no match id")

# U04 auth
rec("U04","guest token /auth/me", get("/api/v1/auth/me",guest.get("token")).status_code==200, "")
rec("U04","invalid token -> 401", get("/api/v1/auth/me","invalid.token.here").status_code==401, "")
rec("U04","guest upload model -> 401", requests.post(API+"/api/v1/models",files={"file":("x.onnx",b"x")},data={"game":"snake","name":"x"},headers=H(guest.get("token"))).status_code==401, "")
rec("U04","verifyuser login", bool(u3.get("token")), u3.get("user",{}).get("username"))

# U05 profile
r=get("/api/v1/profile",u3["token"]); rec("U05","get profile", r.status_code==200, r.text[:120])
r=requests.put(API+"/api/v1/profile",json={"nickname":"x"*25},headers=H(u3["token"])); rec("U05","invalid nickname 25 chars -> 400", r.status_code==400, r.text[:120])
r=requests.put(API+"/api/v1/profile",json={"nickname":"验证用户","signature":"loop verify","avatar":"😊"},headers=H(u3["token"])); rec("U05","valid profile update", r.status_code==200, r.text[:120])
p=get("/api/v1/profile",u3["token"]).json().get("user",{}); rec("U05","profile persisted", p.get("nickname")=="验证用户", p.get("nickname"))

fixture="/home/leoric/code/gameplatform/docs/pm/qa/fixtures/snake-rotwin-min.onnx"
def upload_snake(tok,name):
    with open(fixture,"rb") as f:
        return requests.post(API+"/api/v1/models",files={"file":("snake-rotwin-min.onnx",f,"application/octet-stream")},data={"game":"snake","name":name},headers=H(tok))
# U07 contract
r=upload_snake(u3["token"],"verify-snake-A"); A=(r.json().get("model") or {}).get("id"); rec("U07","valid ONNX upload", r.status_code==200 and bool(A), f"id={A} status={r.status_code}")
with open(fixture,"rb") as f:
    r=requests.post(API+"/api/v1/models",files={"file":("snake-rotwin-min.onnx",f,"application/octet-stream")},data={"game":"tetris","name":"bad-contract"},headers=H(u3["token"]))
rec("U07","wrong-game contract rejected", r.status_code==400, r.text[:160])
r=upload_snake(u3["token"],"verify-snake-B"); B=(r.json().get("model") or {}).get("id")
# U10 list/detail/delete
lst=get("/api/v1/models",u3["token"]).json().get("models",[]); rec("U10","model list contains A", any(m["id"]==A for m in lst), f"{len(lst)} models")
rec("U10","model detail", get(f"/api/v1/models/{A}",u3["token"]).status_code==200, "")
rec("U10","delete model", delete(f"/api/v1/models/{A}",u3["token"]).status_code==200, "")
rec("U10","deleted model 404", get(f"/api/v1/models/{A}",u3["token"]).status_code==404, "")
lst=get("/api/v1/models",u3["token"]).json().get("models",[]); rec("U10","list excludes deleted", all(m["id"]!=A for m in lst), "")

# U24 admin model takedown/restore (use B)
r=post(f"/api/v1/admin/models/{B}/status",{"status":"banned"},adm["token"]); rec("U24","admin ban model", r.status_code==200, r.text[:100])
rec("U24","banned model hidden", get(f"/api/v1/models/{B}",u3["token"]).status_code==404, "")
r=post(f"/api/v1/admin/models/{B}/status",{"status":"active"},adm["token"]); rec("U24","admin restore model", r.status_code==200 and get(f"/api/v1/models/{B}",u3["token"]).status_code==200, r.text[:100])
rec("U24","cleanup model", delete(f"/api/v1/models/{B}",u3["token"]).status_code==200, "")

# U12 AI demo
r=post("/api/v1/snake/play/sessions",{"kind":"pve","seed":7},u3["token"]); psid=(r.json().get("session") or {}).get("id")
state=(r.json().get("session") or {}).get("state")
r=post("/api/snake/ai/action",{"state":state,"strategy":"dqn"},u3["token"]); act=(r.json() or {}).get("action")
rec("U12","AI action for demo", r.status_code==200 and act is not None, f"status={r.status_code} action={act}")
post(f"/api/v1/snake/play/sessions/{psid}/leave",{},u3["token"])

# U14 matchmaking
q1=post("/api/v1/microrts/matchmaking/queue",{"mode":"ranked"},loop["token"]).json()
q2=post("/api/v1/microrts/matchmaking/queue",{"mode":"ranked"},loop2["token"]).json()
mm=None
for i in range(12):
    s=get("/api/v1/microrts/matchmaking/status",loop["token"]).json()
    if s.get("matched") and s.get("session_id"):
        mm=s; break
    time.sleep(0.5)
rec("U14","two users matched", bool(mm), f"q1={q1} q2={q2} mm={mm}")
if mm:
    msid=mm["session_id"]; st=get(f"/api/v1/microrts/play/sessions/{msid}",loop["token"]).json().get("session",{})
    rec("U14","matched session active", st.get("status") in ("waiting","active"), st.get("status"))
    post(f"/api/v1/microrts/play/sessions/{msid}/leave",{},loop["token"])

# U16 leaderboards/ratings
for scope in ("total","weekly"):
    r=get(f"/api/v1/leaderboards/microrts?scope={scope}"); rec("U16",f"leaderboard {scope}", r.status_code==200, f"items={len(r.json().get('items',[]))}")
r=get("/api/v1/ratings/microrts",loop["token"]); rec("U16","ratings", r.status_code==200, r.text[:140])

# U21 UGC upload->submit->approve
zip_path=OUT/"sokoban.zip"
src=pathlib.Path("/home/leoric/code/gameplatform/gdk-ug/examples/sokoban")
with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as z:
    for p in src.rglob("*"):
        if p.is_file(): z.write(p, p.relative_to(src))
slug=None
try:
    import yaml
    yml=yaml.safe_load((src/"game.yaml").read_text())
    slug=yml.get("slug")
except Exception as e:
    rec("U21","parse game.yaml", False, e)
with open(zip_path,"rb") as f:
    r=requests.post(API+"/api/v1/ugc/games",files={"file":("sokoban.zip",f,"application/zip")},data={"changelog":"verify loop"},headers=H(u3["token"]))
gid=(r.json().get("game") or {}).get("id"); rec("U21","upload draft game", r.status_code==200 and bool(gid), f"status={r.status_code} gid={gid} body={r.text[:180]}")
if gid:
    r=post(f"/api/v1/ugc/games/{gid}/submit",{},u3["token"]); rec("U21","submit review", r.status_code==200, r.text[:140])
    r=get("/api/v1/admin/ugc",adm["token"]); pend=[g for g in r.json().get("games",[]) if g.get("status")=="pending"]
    rec("U21","admin pending queue", r.status_code==200 and any(g.get("id")==gid for g in pend), f"pending={[g.get('id') for g in pend]}")
    r=post(f"/api/v1/admin/ugc/{gid}/approve",{},adm["token"]); rec("U21","approve publish", r.status_code==200, r.text[:140])
    r=get("/api/games"); pub=[g.get("id") for g in r.json().get("games",[])]
    rec("U21","published game in catalog", slug in pub if slug else False, f"slug={slug} catalog={pub[:10]}")

# U23 admin ban/unban u3
r=post(f"/api/v1/admin/users/{u3['user']['id']}/status",{"status":"banned"},adm["token"]); rec("U23","ban user", r.status_code==200, r.text[:100])
r=requests.post(API+"/api/v1/auth/login",json={"username":"verifyuser","password":"<test-password>"}); rec("U23","banned user cannot login", r.status_code!=200, f"status={r.status_code}")
r=post(f"/api/v1/admin/users/{u3['user']['id']}/status",{"status":"active"},adm["token"])
r=requests.post(API+"/api/v1/auth/login",json={"username":"verifyuser","password":"<test-password>"}); rec("U23","unban -> login ok", r.status_code==200, f"status={r.status_code}")
u3=login("verifyuser","<test-password>")

# U25 reports
r=post("/api/v1/reports",{"target_type":"user","target_id":loop2["user"]["id"],"reason":"loopback verify"},u3["token"])
rec("U25","create report", r.status_code==200, r.text[:140])
r=get("/api/v1/admin/reports",adm["token"]); opens=r.json().get("reports",[])
rid=next((x["id"] for x in opens if x.get("status")=="open"), None)
rec("U25","admin open reports", r.status_code==200 and rid is not None, f"open={[x.get('id') for x in opens]}")
if rid:
    r=post(f"/api/v1/admin/reports/{rid}/status",{"status":"resolved"},adm["token"]); rec("U25","resolve report", r.status_code==200, r.text[:100])
    r=get("/api/v1/admin/reports?status=resolved",adm["token"]); rec("U25","resolved visible", any(x["id"]==rid for x in r.json().get("reports",[])), "")

# U26 dashboard/admin lists
r=get("/api/v1/admin/dashboard",adm["token"]); rec("U26","dashboard", r.status_code==200 and isinstance(r.json(),dict), f"status={r.status_code}")
for p in ("/api/v1/admin/models","/api/v1/admin/matches","/api/v1/admin/ugc"):
    r=get(p,adm["token"]); rec("U26","admin list "+p, r.status_code==200, f"status={r.status_code}")

# U28 notifications via friend add
r=post("/api/v1/friends",{"username":"loopuser2"},u3["token"]); rec("U29","add friend", r.status_code==200, r.text[:140])
r=get("/api/v1/notifications",loop2["token"]); notifs=r.json().get("items",[]) if r.status_code==200 else []
rec("U28","friend notification delivered", any(n.get("kind")=="friend_add" for n in notifs), f"items={len(notifs)}")
r=get("/api/v1/notifications/unread",loop2["token"]); unread=r.json().get("unread",0); rec("U28","unread count > 0", unread>0, f"unread={unread}")
r=post("/api/v1/notifications/read",{},loop2["token"]); rec("U28","mark all read", r.status_code==200, r.text[:100])
r=get("/api/v1/notifications/unread",loop2["token"]); rec("U28","unread cleared", r.json().get("unread",1)==0, r.text[:100])
# U29 friends remove
fr=get("/api/v1/friends",u3["token"]).json().get("friends",[]); rec("U29","friends list contains", any(f.get("username")=="loopuser2" or f.get("id")==loop2["user"]["id"] for f in fr), f"{[f.get('username') for f in fr]}")
r=delete(f"/api/v1/friends/{loop2['user']['id']}",u3["token"]); rec("U29","remove friend", r.status_code==200, r.text[:100])
fr=get("/api/v1/friends",u3["token"]).json().get("friends",[]); rec("U29","friend removed from list", all(f.get("id")!=loop2["user"]["id"] for f in fr), "")

# U30 errors/permissions
rec("U30","unauth models 401", get("/api/v1/models").status_code==401, "")
rec("U30","non-admin 403", get("/api/v1/admin/dashboard",u3["token"]).status_code==403, "")
rec("U30","unknown game 404", requests.post(API+"/api/v1/nogame/play/sessions",json={},headers=H(u3["token"])).status_code==404, "")
r=post("/api/v1/snake/play/sessions",{"kind":"pve","seed":3},u3["token"]); esid=(r.json().get("session") or {}).get("id")
r=post(f"/api/v1/snake/play/sessions/{esid}/actions",{"actions":999},u3["token"]); rec("U30","invalid action 400", r.status_code==400, f"status={r.status_code}")
post(f"/api/v1/snake/play/sessions/{esid}/leave",{},u3["token"])

LOG["done"]=True
(OUT/"run_rest.json").write_text(json.dumps(LOG,ensure_ascii=False,indent=2))
fails=[s for s in LOG["steps"] if not s["ok"]]
print(f"\nTOTAL {len(LOG['steps'])} steps, FAIL {len(fails)}")
