import requests, time, json
API="http://127.0.0.1:8080"
r=requests.post(API+"/api/v1/auth/login",json={"username":"verifyuser","password":"<test-password>"});r.raise_for_status()
H={"Authorization":"Bearer "+r.json()["token"]}
fixture="/home/leoric/code/gameplatform/docs/pm/qa/fixtures/microrts-rush-min.onnx"
ids=[]
for name in ("mvm-A","mvm-B"):
    with open(fixture,"rb") as f:
        r=requests.post(API+"/api/v1/models",files={"file":("microrts-rush-min.onnx",f,"application/octet-stream")},data={"game":"microrts","name":name},headers=H)
    print("upload",name,r.status_code)
    ids.append(r.json()["model"]["id"])
r=requests.post(API+"/api/v1/matches",json={"game":"microrts","model_a":ids[0],"model_b":ids[1]},headers=H)
print("create match",r.status_code,r.text[:160])
mid=r.json().get("match_id")
res={"model_ids":ids,"match_id":mid,"final":None}
if mid:
    for i in range(90):
        time.sleep(2)
        d=requests.get(API+f"/api/v1/matches/{mid}",headers=H).json()["match"]
        if d.get("status") in ("finished","failed"):
            res["final"]={k:d.get(k) for k in ("status","winner","cause")}
            break
    rep=requests.get(API+f"/api/v1/matches/{mid}/replay").json().get("replay") or {}
    res["replay_moves"]=len(rep.get("moves") or [])
    res["result"]=rep.get("result")
print(json.dumps(res,ensure_ascii=False,indent=1)[:800])
json.dump(res,open("/tmp/loopwalk/u09_mvm.json","w"),ensure_ascii=False,indent=2)
# cleanup models
for mid_model in ids:
    requests.delete(API+f"/api/v1/models/{mid_model}",headers=H)
