# 俄罗斯方块（官方种子游戏包）

- 10×20 棋盘，7-bag 出块；动作 0=左移 1=右移 2=旋转 3=硬降；消行 1/4/9/16 分
- 内置 Dellacherie 启发式 AI（baseline.py）
- 模型契约：simple，obs=grid，in (1,2,20,10) → out (1,4)
- 键盘：方向键/空格（controls 声明）
