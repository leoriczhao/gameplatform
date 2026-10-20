"""游戏包入口：必须暴露 get_adapter()。

把 game.py（或任意模块）里实现契约的类实例返回即可：

    from .game import MyGame
    def get_adapter():
        return MyGame()

契约（docs/design/09，与后端 games/base.py EnvAdapter 一致，duck-typed）：
  info() -> dict                 元数据；应含 schemas.state/action/observations
  new_state(seed, options=None) -> dict   同 seed 必须同轨迹（纯函数）
  step_state(state, action) -> dict       推进一 tick；PvP 时 action = {"p0":…,"p1":…}
  validate_state(state)                   非法 raise ValueError
  validate_action(action, state)          非法 raise ValueError
  obs(state, mode="default")             可选
  opponent_action(state, config)          可选（声明 ai_strategies 时必需）
  sample_action(state)                    可选但强烈建议：返回一个合法动作，
                                          供本地测试器与平台上传 smoke 使用
  score_bounds -> (lo, hi)                榜单分数范围
"""


def get_adapter():
    # TODO: 替换为你的实现
    raise NotImplementedError("在 game.py 中实现契约后，从这里返回实例")
