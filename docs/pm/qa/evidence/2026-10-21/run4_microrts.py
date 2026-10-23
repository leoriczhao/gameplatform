import json, requests, time, pathlib
API="http://127.0.0.1:8080"
r=requests.post(API+"/api/v1/auth/login",json={"username":"loopuser","password":"<test-password>"});r.raise_for_status()
H={"Authorization":"Bearer "+r.json()["token"]}
fixture="/home/leoric/code/gameplatform/docs/pm/qa/fixtures/microrts-rush-min.onnx"
files={"file":("microrts-rush-min.onnx",open(fixture,"rb"),"application/octet-stream")}
r=requests.post(API+"/api/v1/models",files=files,data={"game":"microrts","name":"loop-microrts-min"},headers=H)
print("upload",r.status_code)
print(r.text[:300])
if r.status_code!=200:
    raise SystemExit(1)
mid=r.json()["model"]["id"]
r=requests.post(API+f"/api/v1/models/{mid}/eval",headers=H)
print("eval",r.status_code,r.text[:300])
r=requests.get(API+f"/api/v1/models/{mid}",headers=H)
print("meta",json.dumps(r.json()["model"]["meta"],ensure_ascii=False)[:300])
r=requests.post(API+"/api/v1/matches",json={"game":"microrts","model_a":mid,"model_b":"ai:worker_rush"},headers=H)
print("challenge",r.status_code,r.text[:200])
if r.status_code==200:
    match_id=r.json()["match_id"]
    for i in range(60):
        time.sleep(2)
        d=requests.get(API+f"/api/v1/matches/{match_id}",headers=H).json()["match"]
        if d.get("status")=="finished":
            print("finished",json.dumps({k:d.get(k) for k in ("id","status","winner","cause","tick")},ensure_ascii=False)); break
        if d.get("status")=="failed":
            print("failed",d); break
    rep=requests.get(API+f"/api/v1/matches/{match_id}/replay").json()["replay"]
    print("replay moves",len(rep.get("moves") or []),"result",rep.get("result"))
