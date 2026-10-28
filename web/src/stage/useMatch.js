/* 对局状态与命令（docs/design/17 §7.6）。

   数据流只有一条：首屏用 GET /api/v2/matches/{id} 拿快照，之后所有变化
   都来自 SSE 事件流，命令（出招 / 认输 / 再来一局 / 入座 / 托管）只返回
   确认，结果统一从流里到达（§5.1）。聊天是 REST 轮询（M1 实施记录），
   所以这里单独维护 chat 列表。 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, post } from "../api.js";
import { applySnapshot, reduceMatch } from "./reduceMatch.js";
import { openMatchStream } from "./matchStream.js";

const CHAT_POLL_MS = 2000;

const IDLE_CONNECTION = { state: "idle", attempt: 0, status: null };

export function useMatch(uid, { token = "", enabled = true } = {}) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [connection, setConnection] = useState(IDLE_CONNECTION);
  const [chat, setChat] = useState([]);
  const viewRef = useRef(null);
  const chatSince = useRef(0);

  useEffect(() => {
    if (!uid || !enabled) {
      viewRef.current = null;
      setView(null);
      setError(null);
      setConnection(IDLE_CONNECTION);
      setChat([]);
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();
    let stream = null;
    viewRef.current = null;
    chatSince.current = 0;
    setView(null);
    setError(null);
    setChat([]);
    setConnection({ state: "connecting", attempt: 0, status: null });

    const applyEvent = (event) => {
      const next = reduceMatch(viewRef.current, event);
      viewRef.current = next;
      setView(next);
    };

    (async () => {
      let snapshot;
      try {
        snapshot = await getJson(`/api/v2/matches/${uid}`, token, controller.signal);
      } catch (err) {
        if (cancelled) return;
        setError(err);
        setConnection({ state: "failed", attempt: 0, status: err.status ?? null });
        return;
      }
      if (cancelled) return;
      const initial = applySnapshot(null, snapshot);
      viewRef.current = initial;
      setView(initial);
      // 快照可能是已结束的记录（服务端只回一条 snapshot 就关流），也可能是
      // 刚结束但还没被清扫的直播局（还要收 rematch 事件），两种情况都开流。
      stream = openMatchStream({
        uid,
        token,
        signal: controller.signal,
        onEvent: (event) => {
          if (!cancelled) applyEvent(event);
        },
        onStatus: (status) => {
          if (cancelled) return;
          setConnection(status);
          if (status.state === "failed") {
            setError(Object.assign(new Error(`事件流连接失败（HTTP ${status.status}）`), {
              status: status.status,
            }));
          }
        },
      });
    })();

    return () => {
      cancelled = true;
      controller.abort();
      stream?.close();
    };
  }, [uid, token, enabled]);

  /* 聊天只在"我是玩家且是多人对局"时轮询；失败不打断舞台。 */
  useEffect(() => {
    const seated = Boolean(view?.you?.seat);
    const multi = (view?.seats?.length ?? 0) > 1;
    if (!uid || !enabled || !seated || !multi) return undefined;
    let stopped = false;
    let timer = null;
    const poll = async () => {
      try {
        const data = await getJson(
          `/api/v2/matches/${uid}/chat?since=${chatSince.current}`,
          token,
        );
        if (stopped) return;
        if (Array.isArray(data?.messages) && data.messages.length) {
          setChat((prev) => {
            const known = new Set(prev.map((message) => message.id));
            return [...prev, ...data.messages.filter((message) => !known.has(message.id))];
          });
        }
        if (Number.isFinite(data?.next_since)) chatSince.current = data.next_since;
      } catch (err) {
        /* 聊天不可用（未入座 / 已结束）时静默 */
      }
      if (!stopped) timer = setTimeout(poll, CHAT_POLL_MS);
    };
    poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [uid, token, enabled, view?.you?.seat, view?.seats?.length]);

  const submit = useCallback(async (action) => {
    const current = viewRef.current;
    if (!current) throw new Error("对局还没有载入");
    return post(`/api/v2/matches/${uid}/actions`, { tick: current.tick, action }, token);
  }, [uid, token]);

  const resign = useCallback(
    () => post(`/api/v2/matches/${uid}/resign`, {}, token),
    [uid, token],
  );

  const rematch = useCallback(
    () => post(`/api/v2/matches/${uid}/rematch`, {}, token),
    [uid, token],
  );

  const join = useCallback(
    (seat, invite = null) => post(
      `/api/v2/matches/${uid}/seats/${seat}/join`, { invite }, token,
    ),
    [uid, token],
  );

  const setController = useCallback(
    (seat, controller) => post(
      `/api/v2/matches/${uid}/controller`, { seat, controller }, token,
    ),
    [uid, token],
  );

  const sendChat = useCallback(async (text) => {
    const data = await post(`/api/v2/matches/${uid}/chat`, { text }, token);
    const message = data?.message;
    if (message) {
      setChat((prev) => (prev.some((item) => item.id === message.id) ? prev : [...prev, message]));
      chatSince.current = Math.max(chatSince.current, Number(message.id) || chatSince.current);
    }
    return message;
  }, [uid, token]);

  return {
    view,
    error,
    connection,
    chat,
    actions: { submit, resign, rematch, join, setController, sendChat },
  };
}
