# CHANGE-20261015-qa-onnx-fixture specify

- 要解决的问题：冒烟 H05 / D04 / D05 缺样例 ONNX（FIX-QA-02），长期 blocked；仓内无与 `snake` 契约匹配的小文件。
- 非目标：不建测号（FIX-QA-01）；不上传生产；不训练真实策略；不改上传 API / 契约字段。
- 用户触点：QA 本地/制品侧用夹具文件走「选文件上传」路径（需登录时另等 FIX-QA-01）。
- 成功指标：
  - 仓内有 `<1MB` ONNX，`inference.check_contract(path, "snake")` 通过
  - `docs/pm/qa/fixtures.md` FIX-QA-02 标 **就绪**，写清路径与用法
  - Dev 交 `report-dev.md`；不发版
- 风险：零权模型玩法无意义——仅作契约/上传夹具，勿当评估基线。
