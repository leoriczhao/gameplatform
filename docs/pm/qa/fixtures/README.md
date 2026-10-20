# QA ONNX fixtures

`snake-rotwin-min.onnx` — 最小合规夹具，匹配 `packaged-games/snake/game.yaml` 契约（`in_shape [1,1334]`、`out_shape [1,3]`、`protocol: simple`、`obs_mode: rotwin`）。权重近零，仅用于上传/契约冒烟（H05、D04、D05），不代表可玩策略。上传到现网需登录账号（FIX-QA-01）；本文件不预置生产 model id。
