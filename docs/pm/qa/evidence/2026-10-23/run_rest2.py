import json, time, zipfile, pathlib, re
import requests
API="http://127.0.0.1:8080"
OUT=pathlib.Path("/tmp/loopwalk")
LOG={"steps":[]}
def rec(case,step,ok,detail):
    LOG["steps"].append({"case":case,"step":step,"ok":bool(ok),"detail":str(detail)[:500]})
    print(("PASS" if ok else "FAIL"),case,"|",step,"|",str(detail)[:180])
def login(u,p):
    r=requests.post(API+"/api/v1/auth/login",json={"username":u,"password":p})
    if r.status_code!=200:
        r=requests.post(API+"/api/v1/auth/register",json={"username":u,"password":p})
    r.raise_for_status(); return r.json()
def H(t): return {"Authorization":"Bearer "+t}
def get(p,t=None): return requests.get(API+p,headers=H(t) if t else {})
def post(p,b=None,t=None): return requests.post(API+p,json=b if b is not None else {},headers=H(t) if t else {})
loop=login("loopuser","<test-password>"); adm=login("labadmin","<test-password>"); u3=login("verifyuser","<test-password>")
guest=requests.post(API+"/api/v1/auth/guest").json()
# U04 corrected expectations
rec("U04","guest /me -> 401 by design", get("/api/v1/auth/me",guest["token"]).status_code==401, "")
rec("U04","guest can read scores", get("/api/snake/scores",guest["token"]).status_code==200, "")
rec("U04","guest cannot create play session -> 401", requests.post(API+"/api/v1/snake/play/sessions",json={},headers=H(guest["token"])).status_code==401, "")
# U05 corrected expectations (backend truncates nickname to 24)
r=requests.put(API+"/api/v1/profile",json={"nickname":"x"*25},headers=H(u3["token"]))
prof=(r.json() or {}).get("profile") or {}
rec("U05","overlong nickname handled (truncated to 24)", r.status_code==200 and len(prof.get("nickname",""))==24, f"status={r.status_code} len={len(prof.get('nickname',''))}")
r=requests.put(API+"/api/v1/profile",json={"nickname":"验证用户","signature":"loop verify","avatar":"😊"},headers=H(u3["token"]))
prof=(r.json() or {}).get("profile") or {}
rec("U05","valid update persisted", prof.get("nickname")=="验证用户" and prof.get("avatar")=="😊", f"profile_keys={list(prof.keys())[:6]}")
# U16 with token
for scope in ("total","weekly"):
    r=get(f"/api/v1/leaderboards/microrts?scope={scope}",loop["token"])
    items=(r.json() or {}).get("items",[]) if r.status_code==200 else []
    rec("U16",f"leaderboard {scope}", r.status_code==200, f"status={r.status_code} items={len(items)} sample={items[:2]}")
# U21 retry without __pycache__
zip_path=OUT/"sokoban-clean.zip"
src=pathlib.Path("/home/leoric/code/gameplatform/gdk-ug/examples/sokoban")
with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as z:
    for p in src.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            z.write(p, p.relative_to(src))
import yaml
slug=yaml.safe_load((src/"game.yaml").read_text()).get("slug")
with open(zip_path,"rb") as f:
    r=requests.post(API+"/api/v1/ugc/games",files={"file":("sokoban-clean.zip",f,"application/zip")},data={"changelog":"verify loop"},headers=H(u3["token"]))
gid=(r.json().get("game") or {}).get("id")
rec("U21","upload draft game (clean zip)", r.status_code==200 and bool(gid), f"status={r.status_code} gid={gid} body={r.text[:180]}")
if gid:
    r=post(f"/api/v1/ugc/games/{gid}/submit",{},u3["token"]); rec("U21","submit review", r.status_code==200, r.text[:140])
    r=get("/api/v1/admin/ugc",adm["token"]); games=r.json().get("games",[]) if r.status_code==200 else []
    rec("U21","admin pending queue", r.status_code==200 and any(g.get("id")==gid for g in games), f"statuses={[(g.get('id'),g.get('status')) for g in games[:5]]}")
    r=post(f"/api/v1/admin/ugc/{gid}/approve",{},adm["token"]); rec("U21","approve publish", r.status_code==200, r.text[:140])
    catalog=[g.get("id") for g in get("/api/games").json().get("games",[])]
    rec("U21","published game in catalog", slug in catalog, f"slug={slug} catalog={catalog}")
OUT and (OUT/"run_rest2.json").write_text(json.dumps(LOG,ensure_ascii=False,indent=2))
print("FAILS", [s for s in LOG["steps"] if not s["ok"]])
