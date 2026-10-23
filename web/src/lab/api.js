import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, post, del, uploadFile } from "../api.js";

export { getJson, post, del, uploadFile };

export function useAsync(fn, deps = [], options = {}) {
  const { enabled = true } = options;
  const [state, setState] = useState({ data: null, error: null, loading: Boolean(enabled) });
  const [nonce, setNonce] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false });
      return undefined;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve()
      .then(fn)
      .then((data) => {
        if (!cancelled && alive.current) setState({ data, error: null, loading: false });
      })
      .catch((error) => {
        if (!cancelled && alive.current) setState({ data: null, error, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback(
    (updater) =>
      setState((s) => ({
        ...s,
        data: typeof updater === "function" ? updater(s.data) : updater,
      })),
    [],
  );
  return { ...state, reload, setData };
}

export function useGames() {
  return useAsync(() => getJson("/api/games"), []);
}

export function usePlatformStatus(intervalMs = 10000) {
  const [status, setStatus] = useState({
    ready: false,
    health: null,
    error: null,
    checkedAt: 0,
  });

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const tick = async () => {
      let ready = false;
      let health = null;
      let error = null;
      try {
        await getJson("/api/ready");
        ready = true;
      } catch (e) {
        error = e;
      }
      try {
        health = await getJson("/api/health");
      } catch (e) {
        error = error || e;
      }
      if (!cancelled) {
        setStatus({ ready, health, error, checkedAt: Date.now() });
      }
      timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs]);

  return status;
}

export function useModels(token, enabled) {
  return useAsync(() => getJson("/api/v1/models", token), [token], { enabled });
}

export function useMatches(token, enabled) {
  return useAsync(() => getJson("/api/v1/matches", token), [token], { enabled });
}

export function useMatchReplay(matchId) {
  return useAsync(
    () => getJson(`/api/v1/matches/${matchId}/replay`),
    [matchId],
    { enabled: Boolean(matchId) },
  );
}

export function useLeaderboard(game, token, enabled) {
  return useAsync(
    () => getJson(`/api/v1/leaderboards/${encodeURIComponent(game)}?scope=total`, token),
    [game, token],
    { enabled },
  );
}
