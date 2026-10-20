# 微RTS（官方种子游戏包）

- 16×16 MicroRTS 规则移植；复合动作（每 tick 每单位一条指令）
- 内置策略：worker_rush / light_rush / ranged_rush（PvE 对手 + AI 演示）
- PvP：unit 型，开局参数 {opponent: external}
- 模型契约：composite——model_inputs 逐单位构造 (1,1546)，model_decode 做
  masked-argmax 并组装指令
