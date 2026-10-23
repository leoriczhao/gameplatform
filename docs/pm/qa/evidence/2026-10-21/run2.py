import json, requests, time, pathlib
API="http://127.0.0.1:8080"
OUT=pathlib.Path("/tmp/loopwalk"); OUT.mkdir(exist_ok=True)
def login(u,p):
    r=requests.post(API+"/api/v1/auth/login",json={"username":u,"password":p}); r.raise_for_status(); return r.json()
u=login("loopuser","<test-password>")
H={"Authorization":"Bearer "+u["token"]}
res={}
fixture="/home/leoric/code/gameplatform/docs/pm/qa/fixtures/snake-rotwin-min.onnx"
files={"file":("snake-rotwin-min.onnx",open(fixture,"rb"),"application/octet-stream")}
r=requests.post(API+"/api/v1/models",files=files,data={"game":"snake","name":"loop-snake-min-2"},headers=H)
res["upload"]={"status":r.status_code,"body":r.json()}
mid=r.json()["model"]["id"]
r=requests.post(API+f"/api/v1/models/{mid}/eval",headers=H)
res["eval"]={"status":r.status_code,"body":r.json()}
r=requests.get(API+f"/api/v1/models/{mid}",headers=H)
res["model_after_eval"]={"status":r.status_code,"body":r.json()}
r=requests.get(API+"/api/v1/models",headers=H)
res["models_list"]={"status":r.status_code,"count":len(r.json().get("models",[]))}
r=requests.post(API+"/api/v1/matches",json={"game":"snake","model_a":mid,"model_b":"ai:dqn"},headers=H)
res["challenge_snake_ai"]={"status":r.status_code,"body":r.text[:200]}
(OUT/"run2.json").write_text(json.dumps(res,ensure_ascii=False,indent=2))
print(json.dumps({"model_id":mid,"eval_status":res["eval"]["status"],"persisted":bool(res["model_after_eval"]["body"]["model"]["meta"].get("eval")),"meta":res["model_after_eval"]["body"]["model"]["meta"]},ensure_ascii=False)[:1200])
