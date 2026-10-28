"""What a viewer of a live match may see of the authoritative state.

Platform default: top-level keys starting with "_" are private to the server
(RNG seeds, hidden decks, …). A package may refine this per seat with an
optional ``view(state, seat)`` hook (seat None = spectator); the platform
still drops "_" keys from whatever the hook returns. Finished matches reveal
the full state, so replays stay reproducible.
"""
from __future__ import annotations


def strip_private(state):
    if not isinstance(state, dict):
        return state
    return {k: v for k, v in state.items() if not (isinstance(k, str) and k.startswith("_"))}
