# CHANGE-20261015-qa-onnx-fixture plan

## 范围
- Dev：生成最小合规 ONNX（`snake`：`in [1,1334]` / `out [1,3]` / simple / rotwin），入库 `docs/pm/qa/fixtures/`，ORT + `check_contract` 校验；更新 `fixtures.md` FIX-QA-02；写 `report-dev.md`。
- QA（可选）：FIX-QA-01 就绪后用本文件重跑 H05（及 D04/D05 上传步）；无测号则 H05 仍可标「文件就绪 / 登录 blocked」。
- 不部署；不发明登录账号。

## 派工
1. **Stream Dev**：生成文件 + fixtures 更新 → `report-dev.md`（本轮）
2. **Stream QA**：夹具说明已就绪后按需补跑；结果回填 smoke / report-qa（挂 smoke-lib 或本 CHANGE 附注）
3. **leoric**：FIX-QA-01 测号（本 CHANGE 不挡）

## Done（Dev）
- ONNX 存在且 `check_contract(..., "snake")` 绿
- FIX-QA-02 就绪 + 路径写明
- `report-dev.md`
