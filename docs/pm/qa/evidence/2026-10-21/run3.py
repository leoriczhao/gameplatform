import json, requests, pathlib
API="http://127.0.0.1:8080"
OUT=pathlib.Path("/tmp/loopwalk"); OUT.mkdir(exist_ok=True)
r=requests.post(API+"/api/v1/auth/login",json={"username":"loopuser","password":"<test-password>"});r.raise_for_status();d=r.json()
H={"Authorization":"Bearer "+d["token"]}
res={}
for mid in (1,2,3):
    r=requests.get(API+f"/api/v1/matches/{mid}/replay")
    body=r.json() if r.status_code==200 else {}
    res[f"replay_{mid}"]={"status":r.status_code,"moves":len(body.get("moves") or []),"keys":list(body.keys())[:6]}
# anonymous watch of a public pvp session
r=requests.post(API+"/api/v1/microrts/play/sessions",json={"kind":"pvp","mode":"casual","visibility":"public"},headers=H)
sid=r.json()["session"]["id"]; invite=r.json().get("invite")
res["watch_create"]={"status":r.status_code,"sid":sid,"invite":invite}
r2=requests.get(API+f"/api/v1/microrts/play/sessions/{sid}")
res["watch_anon_get"]={"status":r2.status_code,"body":r2.text[:180]}
# cleanup waiting room
requests.post(API+f"/api/v1/microrts/play/sessions/{sid}/leave",json={},headers=H)
(OUT/"run3.json").write_text(json.dumps(res,ensure_ascii=False,indent=2))
print(json.dumps(res,ensure_ascii=False,indent=1)[:1500])
