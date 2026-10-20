"""Shared per-client HTTP rate limits for platform endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request, cap: float = 60.0,
                user_cap: float | None = None, window: float = 1.0,
                bucket: str = "env", label: str = "env API") -> None:
    """Per-client sliding-window limiter (in-memory, single worker).

    Identity tiering (docs/design/02):
      - registered users (valid bearer JWT) -> user_cap req/s (default 2x cap),
        keyed by user id
      - guests / anonymous                  -> cap req/s, keyed by client IP
    bucket gives each endpoint family its own budget so heavy env training
    traffic cannot consume the scores quota (and vice versa).
    """
    limit, key = cap, None
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        import auth as auth_mod
        payload = auth_mod.decode_token(authz[7:].strip())
        if payload and isinstance(payload.get("sub"), str) and payload["sub"].isdigit():
            key = f"{bucket}:u:{payload['sub']}"
            limit = user_cap if user_cap is not None else cap * 2.0
    if key is None:
        ip = (request.headers.get("x-forwarded-for", "") or
              (request.client.host if request.client else "?")).split(",")[0].strip()
        key = f"{bucket}:ip:{ip}"

    now = time.monotonic()
    q = _hits[key]
    q.append(now)
    while q and now - q[0] > window:
        q.popleft()
    if len(q) > limit:
        q.popleft()
        raise HTTPException(429, f"{label} rate limit exceeded "
                                 f"({limit:.0f} req/s per client)")
    if len(_hits) > 4096:  # avoid unbounded growth of the dict
        cutoff = now - window
        for k in [k for k, v in _hits.items() if not v or v[-1] < cutoff]:
            del _hits[k]
