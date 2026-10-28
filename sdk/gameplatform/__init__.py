"""Stream Python SDK — train your own models against the platform's games.

    # local training (default): the exact game package runs in your process
    from gameplatform import LocalVecEnv
    with LocalVecEnv(game="snake", n=64, obs_mode="rotwin",
                     base_url="https://games.cree1p.com") as envs:
        obs = envs.reset(seed=42)
        obs, rewards, dones, infos = envs.step(actions)

    import gameplatform.gym as gpgym               # registers platform-*-v0
    import gymnasium as gym
    with gym.make("platform-snake-v0", obs_mode="rotwin") as env:  # backend="local"
        obs, info = env.reset()

    # remote environments over official OpenEnv WebSockets (one round trip per step)
    from gameplatform import RemoteVecEnv

    # export + local evaluation + upload + challenge
    from gameplatform import export_onnx, evaluate
    export_onnx(my_net, game=envs.runtime, path="my_dqn.onnx")
    evaluate("my_dqn.onnx", envs.runtime, episodes=20)   # same protocol as the server

    # account + v2 matches. SDK 1.0 is a breaking release: the deleted v1
    # play/room/quick-match APIs are replaced by /api/v2/matches, and
    # SessionClient is now a stateful v2 match client (design 17 §5).
    from gameplatform import PlatformClient, SessionClient
    c = PlatformClient(base_url="https://games.cree1p.com")
    c.login("alice", "secret")
    model = c.upload_model("my_dqn.onnx", game="snake", name="我的DQN")
    uid = c.create_match(game="microrts", model_a=model["id"],
                         model_b="ai:light_rush")

parity_check(game, base_url=...) replays one seeded episode locally and over
OpenEnv and reports the first differing step, if any.
"""

__version__ = "1.0.0"

from .remote import RemoteVecEnv  # noqa: F401
from .local import (LocalGame, LocalVecEnv, evaluate, fetch_package,  # noqa: F401
                    load_game, parity_check)
from .client import PlatformClient, SessionClient, PlatformError  # noqa: F401
from .export import export_onnx  # noqa: F401

__all__ = ["LocalVecEnv", "LocalGame", "load_game", "fetch_package", "evaluate",
           "parity_check", "RemoteVecEnv", "PlatformClient", "SessionClient",
           "PlatformError", "export_onnx", "__version__"]
