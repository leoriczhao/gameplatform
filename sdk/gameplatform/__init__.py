"""Stream Python SDK — train your own models against the platform.

    from gameplatform import RemoteVecEnv          # OpenEnv WS slots, gym-style
    from gameplatform.gym import PlatformRemoteEnv # gymnasium single env
    import gameplatform.gym as gpgym               # registers platform-*-v0
    import gymnasium as gym
    with gym.make("platform-snake-v0", obs_mode="rotwin") as env:
        obs, info = env.reset()

    # export + upload + challenge (accounts / models / matches)
    from gameplatform.export import export_onnx
    export_onnx(my_net, game="snake", path="my_dqn.onnx")

    from gameplatform import PlatformClient, SessionClient
    c = PlatformClient(base_url="https://games.cree1p.com")
    c.login("alice", "secret")
    model = c.upload_model("my_dqn.onnx", game="snake", name="我的DQN")

    s = c.session("microrts")
    s.start_pve(opponent="worker_rush")
    while not s.done:
        s.act(build_commands(s.state))

Environment dynamics use official OpenEnv WebSocket sessions (one per slot).
Model/training compute runs locally; transitions run on the server. Use
RemoteVecEnv as a context manager or call close() to release all sessions.
"""

__version__ = "0.2.0"

from .remote import RemoteVecEnv  # noqa: F401
from .client import PlatformClient, SessionClient, PlatformError  # noqa: F401
from .export import export_onnx  # noqa: F401

__all__ = ["RemoteVecEnv", "PlatformClient", "SessionClient",
           "PlatformError", "export_onnx", "__version__"]
