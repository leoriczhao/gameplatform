# CHANGE-20261015-qa-smoke-lib specify

- 要解决的问题：冒烟覆盖过窄（文档绿、游戏红曾漏测）；用户要求「继续，覆盖多一点」。
- 范围：扩展 `docs/pm/qa/smoke-cases.md`（H 批 + 夹具表）；发版基线 P0 = 原 P0 + G01 + H04 + H08；P1 加深主路径；P2 壳可达。
- 非目标：不改业务代码；不做 ELO/UGC/admin 穷举；不部署。
- 成功：用例入库；QA 跑一版并写本 CHANGE `report-qa.md`（blocked 须写清缺夹具）。
