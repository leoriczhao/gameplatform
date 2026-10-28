/* 对局状态与命令（docs/design/17 §7.6）。

   数据流只有一条：首屏用 GET /api/v2/matches/{id} 拿快照，之后所有变化
   都来自 SSE 事件流，命令（出招 / 认输 / 再来一局 / 入座 / 托管 / 聊天）
   只返回确认，结果统一从流里到达（§5.1）。M4 起聊天也走这条流：快照里的
   chat 是权威历史，chat 事件逐条追加；POST /chat 只做按 id 去重的乐观追加，
   不再 REST 轮询。 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, post } from "../api.js";
import { applySnapshot, reduceMatch } from "./reduceMatch.js";
import { openMatchStream } from "./matchStream.js";

const IDLE_CONNECTION = { state: "idle", attempt: 0, status: null };

export function useMatch(uid, { token = "", enabled = true } = {}) {
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  const [connection, setConnection] = useState(IDLE_CONNECTION);
  const viewRef = useRef(null);

  useEffect(() => {
    if (!uid || !enabled) {
      viewRef.current = null;
      setView(null);
      setError(null);
      setConnection(IDLE_CONNECTION);
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();
    let stream = null;
    viewRef.current = null;
    setView(null);
    setError(null);
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

  /* POST /chat 只返回确认：把返回的消息当作一次本地 chat 事件走 reducer，
     按 id 去重乐观追加；SSE 随后推送同一条 chat 事件时会被 reducer 去重。 */
  const sendChat = useCallback(async (text) => {
    const data = await post(`/api/v2/matches/${uid}/chat`, { text }, token);
    const message = data?.message;
    const current = viewRef.current;
    if (message && current) {
      const next = reduceMatch(current, { type: "chat", seq: current.seq, message });
      viewRef.current = next;
      setView(next);
    }
    return message;
  }, [uid, token]);

  return {
    view,
    error,
    connection,
    actions: { submit, resign, rematch, join, setController, sendChat },
  };
}
