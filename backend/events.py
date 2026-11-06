"""In-process domain events (L2, docs/design/19 §5).

The match domain announces what happened; business features (XP, boards,
…) subscribe instead of being called from game flow code. Delivery is
synchronous and in order. A failing subscriber is logged and never breaks the
match that emitted the event.

    match_finished(sess)   a PvE or PvP session reached its result (once per session)
"""
from __future__ import annotations

import logging
from collections import defaultdict

log = logging.getLogger(__name__)
_SUBSCRIBERS: dict[str, list] = defaultdict(list)


def subscribe(name: str, handler) -> None:
    if handler not in _SUBSCRIBERS[name]:
        _SUBSCRIBERS[name].append(handler)


def emit(name: str, payload) -> None:
    for handler in list(_SUBSCRIBERS[name]):
        try:
            handler(payload)
        except Exception:
            log.exception("event %s: subscriber %r failed", name, handler)
