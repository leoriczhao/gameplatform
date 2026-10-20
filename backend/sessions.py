"""Session service — server-side authoritative game sessions (v1.0).

Design: docs/design/03（PvE/PvP 流程）+ 06（房间/匹配）。

- The server holds the authoritative game state; clients submit actions.
- One engine: every tick advances through games/*/EnvAdapter.step_state.
- PvE: single participant (guest or user); games that declare `opponents`
  carry a server-side opponent (built-in strategy, model, or external bot).
- PvP: waiting rooms (mode/visibility) → active → finished; timeout policy,
  resign, rematch (sides swapped); matchmaking fills rooms internally.
- Reconnect entry: active_sessions() for the 回到对局 banner (06 §7 U5).
- Replay: per-tick action log, rebuilt by applying moves through the env API.
- Sessions live in memory (D12); finished results are recorded via matches.
"""
from __future__ import annotations

import os
import random
import string
import threading
import time
import uuid

import httpx

import growth
import inference
import models as model_store
from registry import GAMES, resolve

MAX_GUEST_SESSIONS = 3  # 游客：多留 2 个缓冲，避免跨游戏导航时上一局未释放就 429
MAX_USER_SESSIONS = 8
IDLE_TIMEOUT = 30 * 60  # seconds
PVP_TIMEOUT = float(os.environ.get("PVP_TIMEOUT", "60"))      # per-move wait
PVP_MAX_TIMEOUTS = int(os.environ.get("PVP_MAX_TIMEOUTS", "5"))  # auto-loss


class PlaySession:
    def __init__(self, game: str, principal: dict, seed: int,
                 opponent: dict | None, state: dict,
                 controller: dict | None = None, kind: str = "pve",
                 invite: str | None = None,
                 mode: str = "ranked", visibility: str = "private",
                 settings: dict | None = None,
                 env_options: dict | None = None,
                 game_version: str | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.game = game
        self.seed = seed
        self.kind = kind
        self.principal = principal
        self.principal_key = (principal.get("id") is not None,
                              principal.get("username", "?"))
        self.opponent = opponent  # None | {"type":"ai","strategy":…} | {"type":"model","model_id":…} | {"type":"external_bot","url":…}
        self.controller = controller  # None (human) | {"type":"model","model_id":…}
        self.controller_sess = None   # lazily loaded onnxruntime session
        self.state = state
        self.status = "active"
        self.winner = None
        self.cause = None
        self.moves: list[dict] = []  # replay log
        self.lock = threading.Lock()
        self.created_at = time.time()
        self.updated_at = time.time()
        # pvp-only
        self.invite = invite
        self.from_matchmaking = False  # 匹配撮合的对局默认可观战（06 §7）
        self.mode = mode              # ranked | casual（对局是否结算 ELO）
        self.visibility = visibility  # public | private（是否进大厅公开列表）
        self.settings = dict(settings or {})  # 开局参数（v1 仅 seed）
        self.env_options = dict(env_options) if env_options is not None else None
        self.game_version = game_version
        self._adapter = resolve(game, game_version)
        self.p0 = principal if kind == "pvp" else None
        self.p1 = None
        self.pending = {"p0": None, "p1": None}
        self.submitted_at = {"p0": 0.0, "p1": 0.0}
        self.timeouts = {"p0": 0, "p1": 0}

    def side_of(self, principal: dict) -> str:
        if self.kind != "pvp":
            return "p0"
        if self.p1 and principal.get("id") == self.p1["id"]:
            return "p1"
        if self.p0 and principal.get("id") == self.p0["id"]:
            return "p0"
        raise PermissionError("not a player of this session")

    def adapter(self):
        if self.game not in GAMES:
            raise RuntimeError(f"game {self.game!r} is unavailable")
        return self._adapter

    def controller_action(self):
        """Model autopilot: server computes the player's action."""
        model = model_store.get_model(int(self.controller["model_id"]))
        if model is None or model["status"] != "active":
            raise RuntimeError("controller model unavailable")
        if self.controller_sess is None:
            self.controller_sess = model_store.load_session(model)
        return inference.model_action(self.game, self.controller_sess,
                                      self.state, owner=0, adapter=self.adapter())


_SESSIONS: dict[str, PlaySession] = {}
_STORE_LOCK = threading.Lock()


def _opponent_commands(game: str, state: dict, opponent: dict, adapter=None):
    """Server-side opponent commands for microrts-style games."""
    adapter = adapter or GAMES[game]
    if opponent["type"] == "ai":
        return adapter.opponent_action(state, opponent)
    if opponent["type"] == "model":
        model = model_store.get_model(int(opponent["model_id"]))
        if model is None or model["status"] != "active":
            raise ValueError(f"model {opponent['model_id']} not found")
        return inference.model_action(game, model_store.load_session(model),
                                      state, owner=1, adapter=adapter)
    if opponent["type"] == "external_bot":
        resp = httpx.post(opponent["url"], json={"state": state},
                          timeout=2.5, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        action = data.get("action") if isinstance(data, dict) else data
        if not isinstance(action, list):
            raise ValueError("external bot must return {'action': [cmds]} or a bare list")
        return action
    raise ValueError(f"unsupported opponent type {opponent['type']!r}")


def create_session(game: str, principal: dict, seed: int | None,
                   opponent: dict | None, controller: dict | None = None) -> PlaySession:
    if game not in GAMES:
        raise KeyError(f"unknown game {game!r}")
    adapter = GAMES[game]
    seed = int(seed) if seed is not None else int(time.time() * 1000) % (1 << 30)
    opponents = getattr(adapter, "opponents", None) or []
    if opponents:
        # 声明服务端对手的游戏（13 G3）：p0=玩家，p1=平台合成
        # （内置策略 / 上传模型 / external_bot）
        if opponent is None:
            default = getattr(adapter, "default_opponent", None) or opponents[0]
            opponent = {"type": "ai", "strategy": default}
        if opponent.get("type") not in ("ai", "model", "external_bot"):
            raise ValueError("opponent type must be 'ai' | 'model' | 'external_bot'")
        if opponent.get("type") == "model":
            m = model_store.get_model(int(opponent["model_id"]))
            if m is None or m["status"] != "active":
                raise ValueError(f"model {opponent.get('model_id')} not found")
        env_options = getattr(adapter, "pvp_options", None)
        state = adapter.new_state(seed, env_options)
    else:
        if opponent is not None:
            raise ValueError(f"game {game!r} has no opponent (single-player)")
        env_options = None
        state = adapter.new_state(seed)
    if controller is not None:
        if controller.get("type") != "model":
            raise ValueError("controller type must be 'model'")
        if not principal.get("id"):
            raise PermissionError("模型代打需要登录")
        m = model_store.get_model(int(controller["model_id"]))
        if m is None or m["status"] != "active" or m["owner_id"] != principal["id"]:
            raise ValueError("controller model not found or not yours")
    meta = getattr(adapter, "meta", None) or {}
    sess = PlaySession(game, principal, seed, opponent, state, controller,
                       env_options=env_options,
                       game_version=meta.get("version"))

    # concurrent session cap per principal
    cap = MAX_USER_SESSIONS if principal.get("id") else MAX_GUEST_SESSIONS
    key = f"u:{principal['id']}" if principal.get("id") else f"g:{principal['username']}"
    with _STORE_LOCK:
        active = [s for s in _SESSIONS.values()
                  if s.status == "active" and
                  (f"u:{s.principal['id']}" if s.principal.get("id")
                   else f"g:{s.principal['username']}") == key]
        if len(active) >= cap:
            raise PermissionError(
                f"concurrent session limit reached ({cap})")
        _SESSIONS[sess.id] = sess
    return sess


def get_session(session_id: str) -> PlaySession | None:
    return _SESSIONS.get(session_id)


def _check_tick(sess: PlaySession, expected_tick: int | None) -> None:
    """Optimistic concurrency guard: stale clients must re-poll (409)."""
    if expected_tick is None:
        return
    current = sess.state.get("tick", 0)
    if expected_tick != current:
        raise RuntimeError(f"tick mismatch: expected {expected_tick}, "
                           f"current {current}; refresh and retry")


def step_session(sess: PlaySession, action,
                 expected_tick: int | None = None) -> dict:
    """Advance one tick with the player's action (+server opponent if any).
    `action` may be None when the session's controller is a hosted model."""
    if sess.status != "active":
        raise RuntimeError(f"session is {sess.status}")
    adapter = sess.adapter()
    with sess.lock:
        _check_tick(sess, expected_tick)
        if sess.state.get("done"):
            raise RuntimeError("game already finished")
        if action is None and sess.controller is not None:
            action = sess.controller_action()
        elif action is None:
            raise ValueError("actions required (human controller)")
        if sess.opponent is not None:
            # validate only the player's side; the opponent commands are
            # composed server-side and are always valid by construction
            adapter.validate_action({"p0": action, "p1": []}, sess.state)
            opp = _opponent_commands(sess.game, sess.state, sess.opponent, adapter)
            combined = {"p0": action, "p1": opp}
        else:
            adapter.validate_action(action, sess.state)  # ValueError -> 400 upstream
            opp = None
            combined = action
        nxt = adapter.step_state(sess.state, combined)
        sess.moves.append({"tick": sess.state.get("tick", 0),
                           "action": action,
                           "opponent": opp if sess.opponent is not None else None})
        sess.state = nxt
        sess.updated_at = time.time()
        if nxt.get("done"):
            sess.status = "finished"
            sess.winner = nxt.get("winner")
            sess.cause = nxt.get("cause")
            if not getattr(sess, "_xp_awarded", False):
                growth.award_pve(sess)   # 08 §1; registered users only
                sess._xp_awarded = True
        return nxt


def leave_session(sess: PlaySession, reason: str = "abandon") -> None:
    with sess.lock:
        if sess.status == "active":
            sess.status = "abandoned"
            sess.cause = reason
        sess.updated_at = time.time()


def public_session(sess: PlaySession) -> dict:
    out = {
        "id": sess.id, "game": sess.game, "kind": sess.kind,
        "status": sess.status, "tick": sess.state.get("tick", 0),
        "state": sess.state, "winner": sess.winner, "cause": sess.cause,
        "opponent": ({"type": sess.opponent["type"]}
                     if sess.opponent else None),
        "side": "p0",
        "game_version": sess.game_version,
        "match_id": getattr(sess, "_match_id", None),
    }
    if sess.kind == "pvp":
        out["invite"] = sess.invite
        out["mode"] = sess.mode
        out["visibility"] = sess.visibility
        out["players"] = [
            {"name": sess.p0["nickname"] or sess.p0["username"], "side": "p0",
             "submitted": sess.pending["p0"] is not None},
            {"name": (sess.p1["nickname"] or sess.p1["username"]) if sess.p1 else None,
             "side": "p1", "submitted": sess.pending["p1"] is not None,
             } if sess.p1 else None,
        ]
        out["players"] = [p for p in out["players"] if p]
        out["p1_joined"] = sess.p1 is not None
    return out


def session_replay(sess: PlaySession) -> dict:
    players = [{"name": sess.principal.get("nickname", "?"), "side": "p0"}]
    if sess.kind == "pvp":
        players = [
            {"name": (sess.p0["nickname"] or sess.p0["username"]), "side": "p0"},
            {"name": (sess.p1["nickname"] or sess.p1["username"]) if sess.p1 else "?", "side": "p1"},
        ]
    return {
        "schema_version": 1,
        "id": sess.id, "game": sess.game, "kind": sess.kind,
        "game_version": sess.game_version,
        "seed": sess.seed,
        "options": sess.env_options,
        "players": players,
        "opponent": sess.opponent,
        "moves": sess.moves,
        "result": {"status": sess.status, "winner": sess.winner,
                   "cause": sess.cause},
    }


# ------------------------------------------------------------------- PvP

def _invite_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase + "0123456789", k=6))
        if not any(s.kind == "pvp" and s.invite == code and s.status in ("waiting", "active")
                   for s in _SESSIONS.values()):
            return code


def create_pvp_session(game: str, principal: dict, invite: str | None = None,
                       seed: int | None = None, mode: str = "ranked",
                       visibility: str = "private",
                       settings: dict | None = None) -> PlaySession:
    """Create or join a 人 vs 人 session. Raises ValueError/PermissionError.

    Backward compatibility (06 §4.2): bare `{kind:"pvp"}` = ranked/private.
    The rooms endpoints pass explicit mode/visibility; D10: lobby rooms
    default casual, ranked friend rooms require the host to opt in.
    """
    if not principal.get("id"):
        raise PermissionError("PvP 需要登录")
    adapter = GAMES[game]
    if not getattr(adapter, "pvp_enabled", False):
        raise ValueError(f"游戏 {game!r} 不支持 PvP")
    if mode not in ("ranked", "casual"):
        raise ValueError("mode 必须是 ranked 或 casual")
    if visibility not in ("public", "private"):
        raise ValueError("visibility 必须是 public 或 private")

    if invite:
        code = invite.strip().upper()
        with _STORE_LOCK:
            target = next((s for s in _SESSIONS.values()
                           if s.kind == "pvp" and s.invite == code
                           and s.status == "waiting" and s.p1 is None), None)
            if target is None:
                raise ValueError("邀请码无效或对局已满")
            if target.p0["id"] == principal["id"]:
                raise ValueError("不能加入自己创建的对局")
            target.p1 = principal
            target.status = "active"
            target.updated_at = time.time()
            return target

    if settings and settings.get("seed") is not None:
        seed = settings["seed"]
    seed = int(seed) if seed is not None else int(time.time() * 1000) % (1 << 30)
    env_options = getattr(adapter, "pvp_options", None)
    state = adapter.new_state(seed, env_options)
    meta = getattr(adapter, "meta", None) or {}
    sess = PlaySession(game, principal, seed, None, state, kind="pvp",
                       invite=_invite_code(), mode=mode,
                       visibility=visibility, settings=settings,
                       env_options=env_options,
                       game_version=meta.get("version"))
    sess.status = "waiting"
    _cap_check(principal)
    with _STORE_LOCK:
        _SESSIONS[sess.id] = sess
    return sess


def list_public_rooms(game: str, mode: str | None = None) -> list[dict]:
    """Waiting public PvP rooms for one game (D12: in-memory, restart loses
    them). Optional `mode` filter (ranked|casual)."""
    with _STORE_LOCK:
        rooms = [
            {"id": s.id, "game": s.game, "mode": s.mode,
             "visibility": s.visibility, "invite": s.invite,
             "host": s.p0["nickname"] or s.p0["username"],
             "host_id": s.p0["id"],
             "created_at": s.created_at, "updated_at": s.updated_at}
            for s in _SESSIONS.values()
            if s.kind == "pvp" and s.game == game
            and s.visibility == "public" and s.status == "waiting"
            and s.p1 is None
        ]
    rooms.sort(key=lambda r: r["created_at"])
    if mode:
        rooms = [r for r in rooms if r["mode"] == mode]
    return rooms


def pair_room(sess: PlaySession, principal: dict) -> None:
    """Fill the p1 seat and start the game (room join + matchmaking).
    Callers do their own invite/self-join checks. Raises ValueError."""
    with sess.lock:
        if sess.status != "waiting" or sess.p1 is not None:
            raise ValueError("房间已满或已开始")
        sess.p1 = principal
        sess.status = "active"
        sess.updated_at = time.time()


def join_room_session(game: str, principal: dict, room_id: str,
                      invite: str | None = None) -> PlaySession:
    """Join a waiting room by id. public rooms need no invite; private rooms
    must present the correct invite code. Raises ValueError (400 upstream)."""
    if not principal.get("id"):
        raise PermissionError("PvP 需要登录")
    sess = _SESSIONS.get(room_id)
    if sess is None or sess.kind != "pvp" or sess.game != game:
        raise KeyError("房间不存在")
    with sess.lock:
        if sess.status != "waiting" or sess.p1 is not None:
            raise ValueError("房间已满或已开始")
        if sess.visibility == "private" and (
                not invite or invite.strip().upper() != sess.invite):
            raise ValueError("邀请码无效")
        if sess.p0["id"] == principal["id"]:
            raise ValueError("不能加入自己创建的房间")
    pair_room(sess, principal)
    return sess


def has_active_pvp_pair(game: str, uid0: int, uid1: int) -> bool:
    """Whether these two users already have an unfinished PvP session for
    this game (06 §5.2: don't re-match the same pair while it's running)."""
    with _STORE_LOCK:
        return any(
            s.kind == "pvp" and s.game == game and s.p1 is not None
            and s.status in ("waiting", "active")
            and {s.p0["id"], s.p1["id"]} == {uid0, uid1}
            for s in _SESSIONS.values())


def active_session_count() -> int:
    """Unfinished sessions right now (admin dashboard metric)."""
    with _STORE_LOCK:
        return sum(1 for s in _SESSIONS.values()
                   if s.status in ("waiting", "active"))


def online_user_ids() -> set[int]:
    """Users with an unfinished session right now — a lightweight
    presence proxy used for the friends list 对局中 tag (v1.0-b)."""
    with _STORE_LOCK:
        ids: set[int] = set()
        for s in _SESSIONS.values():
            if s.status not in ("waiting", "active"):
                continue
            if s.kind == "pvp":
                ids.add(s.p0["id"])
                if s.p1:
                    ids.add(s.p1["id"])
            elif s.principal.get("id"):
                ids.add(s.principal["id"])
        return ids


def active_sessions(principal: dict) -> list[dict]:
    """All of one user's unfinished (waiting/active) sessions with the
    caller's side — the reconnect entry point (06 §7 U5)."""
    uid = principal.get("id")
    found: list[tuple[PlaySession, str]] = []
    with _STORE_LOCK:
        for s in _SESSIONS.values():
            if s.status not in ("waiting", "active"):
                continue
            if s.kind == "pvp":
                if uid is None:
                    continue
                in_game = s.p0["id"] == uid or (s.p1 is not None
                                                 and s.p1["id"] == uid)
                if not in_game:
                    continue
                side = "p0" if s.p0["id"] == uid else "p1"
            else:
                if s.principal_key != (uid is not None,
                                      principal.get("username", "?")):
                    continue
                side = "p0"
            found.append((s, side))
    found.sort(key=lambda t: t[0].updated_at, reverse=True)
    out = []
    for s, side in found:
        pub = public_session(s)
        pub["side"] = side
        pub["created_at"] = s.created_at
        pub["updated_at"] = s.updated_at
        out.append(pub)
    return out


def rematch_session(game: str, principal: dict, session_id: str) -> PlaySession:
    """Rematch (06 §7 U7): only a finished PvP session, only its two
    players. Copies settings/mode/visibility, swaps p0/p1, and starts a new
    room with both players back in it (auto-start: both sides already
    agreed by clicking 再来一局). Idempotent: repeated calls return the
    same rematch room while it is still waiting/active."""
    if not principal.get("id"):
        raise PermissionError("再来一局需要登录")
    sess = _SESSIONS.get(session_id)
    if sess is None or sess.kind != "pvp" or sess.game != game:
        raise KeyError("对局不存在")
    with sess.lock:
        if sess.status != "finished":
            raise ValueError("仅已结束的对局可以再来一局")
        if principal["id"] not in (sess.p0["id"], sess.p1["id"]):
            raise PermissionError("只有对局双方可以再来一局")
        if getattr(sess, "_rematch_id", None):
            existing = _SESSIONS.get(sess._rematch_id)
            if existing is not None and existing.status in ("waiting", "active"):
                return existing
            sess._rematch_id = None
    adapter = GAMES[game]
    new_p0, new_p1 = dict(sess.p1), dict(sess.p0)   # sides swapped
    settings = dict(sess.settings)
    seed = settings.get("seed", sess.seed)
    seed = int(seed) if seed is not None else int(time.time() * 1000) % (1 << 30)
    env_options = getattr(adapter, "pvp_options", None)
    state = adapter.new_state(seed, env_options)
    meta = getattr(adapter, "meta", None) or {}
    new_sess = PlaySession(game, new_p0, seed, None, state, kind="pvp",
                           invite=_invite_code(), mode=sess.mode,
                           visibility=sess.visibility, settings=settings,
                           env_options=env_options,
                           game_version=meta.get("version"))
    new_sess.p1 = new_p1
    new_sess.status = "active"
    _cap_check(new_p0)
    _cap_check(new_p1)
    with _STORE_LOCK:
        _SESSIONS[new_sess.id] = new_sess
        sess._rematch_id = new_sess.id
    return new_sess


def _cap_check(principal: dict) -> None:
    cap = MAX_USER_SESSIONS if principal.get("id") else MAX_GUEST_SESSIONS
    key = f"u:{principal['id']}" if principal.get("id") else f"g:{principal['username']}"
    with _STORE_LOCK:
        active = [s for s in _SESSIONS.values()
                  if s.status in ("active", "waiting") and
                  (f"u:{s.principal['id']}" if s.principal.get("id")
                   else f"g:{s.principal['username']}") == key]
        if len(active) >= cap:
            raise PermissionError(f"concurrent session limit reached ({cap})")


def _advance(sess: PlaySession) -> dict:
    """Both sides' commands are in: run one authoritative tick."""
    adapter = sess.adapter()
    combined = {"p0": sess.pending["p0"], "p1": sess.pending["p1"]}
    sess.pending = {"p0": None, "p1": None}
    nxt = adapter.step_state(sess.state, combined)
    sess.moves.append({"tick": sess.state.get("tick", 0), "action": combined})
    sess.state = nxt
    sess.updated_at = time.time()
    if nxt.get("done"):
        sess.status = "finished"
        sess.winner = nxt.get("winner")
        sess.cause = nxt.get("cause")
    return nxt


def pvp_poll(sess: PlaySession) -> dict:
    """Timeout policy: a side that keeps the other waiting for PVP_TIMEOUT
    seconds auto-waits (empty commands); after PVP_MAX_TIMEOUTS it forfeits.
    When both sides hold commands (including auto-waits) the tick advances,
    so an AFK opponent makes the game progress even if nobody submits."""
    now = time.time()
    if sess.status != "active" or sess.p1 is None:
        return {}
    adapter = sess.adapter()
    empty = getattr(adapter, "pvp_empty_action", [])
    events = {}
    for side, other in (("p0", "p1"), ("p1", "p0")):
        if sess.pending[side] is None and sess.pending[other] is not None:
            if now - sess.submitted_at[other] > PVP_TIMEOUT:
                if empty is None:
                    # choice 型无空走子：超时直接判负
                    sess.status = "finished"
                    sess.winner = 0 if other == "p0" else 1
                    sess.cause = "timeout"
                    events["timed_out"] = side
                    break
                sess.pending[side] = empty
                sess.timeouts[side] += 1
                events["timed_out"] = side
                if sess.timeouts[side] >= PVP_MAX_TIMEOUTS:
                    winner = 0 if other == "p0" else 1
                    sess.status = "finished"
                    sess.winner = winner
                    sess.cause = "timeout"
    if sess.status == "active" and sess.pending["p0"] is not None \
            and sess.pending["p1"] is not None:
        _advance(sess)
        events["advanced"] = True
    return events


def pvp_step(sess: PlaySession, principal: dict, action,
             expected_tick: int | None = None) -> dict:
    """Submit this side's commands; advance one tick when both are in."""
    if sess.status != "active":
        raise RuntimeError(f"session is {sess.status}")
    side = sess.side_of(principal)
    adapter = sess.adapter()
    with sess.lock:
        pvp_poll(sess)
        _check_tick(sess, expected_tick)
        if sess.status != "active":
            return {"state": sess.state, "advanced": False,
                    "done": True, "winner": sess.winner, "cause": sess.cause}
        # validate only this side's commands（未提交方用 pvp_empty_action 占位）
        empty = getattr(adapter, "pvp_empty_action", [])
        if side == "p0":
            adapter.validate_action({"p0": action, "p1": empty}, sess.state)
        else:
            adapter.validate_action({"p0": empty, "p1": action}, sess.state)
        sess.pending[side] = action
        sess.submitted_at[side] = time.time()
        sess.updated_at = time.time()

        if sess.pending["p0"] is None or sess.pending["p1"] is None:
            return {"state": sess.state, "advanced": False,
                    "waiting_for": "p0" if sess.pending["p0"] is None else "p1",
                    "done": False}

        nxt = _advance(sess)
        return {"state": nxt, "advanced": True, "done": nxt.get("done", False),
                "winner": sess.winner, "cause": sess.cause}


def pvp_resign(sess: PlaySession, principal: dict) -> None:
    """Resign: the other side wins the match. A waiting room's owner may
    cancel it before anyone joins."""
    side = sess.side_of(principal)
    with sess.lock:
        if sess.status == "waiting" and side == "p0":
            sess.status = "cancelled"
            sess.updated_at = time.time()
            return
        if sess.status != "active":
            return
        sess.status = "finished"
        sess.cause = "resigned"
        sess.winner = 1 if side == "p0" else 0
        sess.updated_at = time.time()


def cleanup() -> None:
    """Drop abandoned/finished sessions after a grace period and idle active
    ones. Called periodically by the API layer."""
    now = time.time()
    with _STORE_LOCK:
        for sid in [s for s, sess in _SESSIONS.items()
                    if (sess.status not in ("active", "waiting")
                        and now - sess.updated_at > 3600)
                    or (sess.status in ("active", "waiting")
                        and now - sess.updated_at > IDLE_TIMEOUT)]:
            del _SESSIONS[sid]
