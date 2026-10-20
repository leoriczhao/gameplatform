"""Client-side observation functions registry, keyed by game id.

Each entry maps an obs_mode name to a factory (R) -> fn(state) -> np.ndarray.
Server-side obs modes (OpenEnv state()["environment"]["obs_modes"]) are
handled by the platform automatically — this registry only covers modes the
client computes locally from raw states.
"""
from . import snake_features

OBS_FUNCTIONS: dict[str, dict[str, callable]] = {
    "snake": {
        "features": lambda R: (lambda state:
                               snake_features.relative_features(
                                   snake_features.StateAdapter(state))),
        "rotwin": lambda R: (lambda state:
                             snake_features.rotwin_features(
                                 snake_features.StateAdapter(state), R)),
        "reach": lambda R: (lambda state:
                            snake_features.reachability_features(
                                snake_features.StateAdapter(state))),
    },
}


def make_obs_fn(game: str, obs_mode: str, R: int = 4):
    """Return fn(state) -> np.ndarray for a client-side obs mode, or None."""
    modes = OBS_FUNCTIONS.get(game, {})
    if obs_mode in modes:
        return modes[obs_mode](R)
    return None
