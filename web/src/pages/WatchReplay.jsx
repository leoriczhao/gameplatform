import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ClapperboardIcon, Share2Icon, SwordsIcon, PlayIcon, PauseIcon,
  SkipBackIcon, SkipForwardIcon,
} from "lucide-react";
import UgBoard from "../components/UgBoard.jsx";
import { getJson } from "../api.js";
import { rebuildReplay } from "../replay.js";
import { Button } from "../components/ui/button.jsx";
import { Badge } from "../components/ui/badge.jsx";
import { Alert } from "../components/ui/alert.jsx";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card.jsx";
import { Slider } from "../components/ui/slider.jsx";
import { Progress } from "../components/ui/progress.jsx";
import { Stat } from "../components/ui/stat.jsx";
import { PageHeader } from "../components/ui/page-header.jsx";

/* moves 存的是每 tick 双方指令，不是状态；用记录的 version/seed/options
   在同一个官方 OpenEnv WS 环境内逐 tick 重建。缺少版本/seed 时明示失败。 */
const CAUSE_LABEL = { destroyed: "全歼", time: "时间到", resigned: "认输", timeout: "超时判负" };
const SIDE_NAME = { p0: "蓝方", p1: "红方" };

export default function WatchReplay() {
  const { matchId } = useParams();
  const [replay, setReplay] = useState(null);
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);
  const [states, setStates] = useState([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const stateRef = useRef(null);
  const [, setUiTick] = useState(0);
  const bump = useCallback(() => setUiTick((t) => t + 1), []);
  const emptySelRef = useRef(null);
  const emptyHoverRef = useRef(null);
  const emptyFlashRef = useRef([]);

  useEffect(() => {
    const controller = new AbortController();
    setReplay(null); setStates([]); setMeta(null); setError(null); setIdx(0); setPlaying(false);
    setProgress({ done: 0, total: 0 });
    (async () => {
      try {
        const { replay: record } = await getJson(`/api/v1/matches/${matchId}/replay`, null, controller.signal);
        if (controller.signal.aborted) return;
        setReplay(record);
        setProgress({ done: 0, total: record.moves.length + 1 });
        await rebuildReplay(record, { signal: controller.signal,
          onProgress: (built, metadata) => {
            if (controller.signal.aborted) return;
            setStates(built); setMeta(metadata);
            setProgress({ done: built.length, total: record.moves.length + 1 });
          },
        });
      } catch (e) {
        if (!controller.signal.aborted) setError(`回放重建失败：${e.message}`);
      }
    })();
    return () => controller.abort();
  }, [matchId]);

  /* 3. playback timer */
  useEffect(() => {
    if (!playing) return undefined;
    const t = setInterval(() => {
      setIdx((i) => {
        if (i >= states.length - 1) { setPlaying(false); return i; }
        return i + 1;
      });
    }, 800 / speed);
    return () => clearInterval(t);
  }, [playing, speed, states.length]);

  useEffect(() => {
    stateRef.current = states[idx] || null;
    bump();
  }, [idx, states, bump]);

  const share = async () => {
    const url = `${window.location.origin}/watch/match/${matchId}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("分享链接已复制，任何人打开即可观看回放");
    } catch (e) {
      toast.warning(`手动复制：${url}`);
    }
  };

  const s = stateRef.current;
  const loaded = states.length > 0;
  const loading = replay && !error && progress.done < progress.total;
  const maxTick = Math.max(states.length - 1, 0);
  const pct = progress.total ? Math.round((100 * progress.done) / progress.total) : 0;
  const winnerName = replay && replay.result.winner != null
    ? (replay.players || []).find((p) => p.side === `p${replay.result.winner}`)?.name
      || `p${replay.result.winner}`
    : null;

  return (
    <div className="page-shell">
      <PageHeader
        icon={ClapperboardIcon}
        title={`对局回放 #${matchId}`}
        description="逐 tick 重建对局状态 · 步进 / 播放 / 调速 · 分享链接任何人可直接打开"
        actions={(
          <>
            {replay && (
              <Badge variant={replay.mode === "ranked" ? "warning" : "success"}>
                {replay.mode === "ranked" ? "排位" : "练习"}
              </Badge>
            )}
            <Button size="sm" variant="outline" onClick={share}>
              <Share2Icon /> 分享链接
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link to="/records"><SwordsIcon /> 战绩</Link>
            </Button>
          </>
        )}
      />

      {error && <Alert variant="warning" className="mb-6"><div>{error}</div></Alert>}

      {replay && !error && (
        <>
          <Alert variant="info" className="mb-4">
            <div>
              <div className="mb-0.5 font-semibold leading-none tracking-tight">
                {(replay.players || []).map((p) => `${SIDE_NAME[p.side] || p.side} ${p.name}`).join("  vs  ")}
              </div>
              <div className="mt-1 text-sm opacity-90">
                {replay.result.winner == null
                  ? `平局（${CAUSE_LABEL[replay.result.cause] || replay.result.cause}）· 共 ${states.length || replay.moves.length} tick`
                  : `${winnerName} 获胜（${CAUSE_LABEL[replay.result.cause] || replay.result.cause}）· 共 ${states.length || replay.moves.length} tick`}
              </div>
            </div>
          </Alert>
          {loading && (
            <div className="mb-4 flex items-center gap-3">
              <Progress value={pct} className="flex-1" />
              <span className="shrink-0 text-xs text-muted-foreground">
                重建回放中… {progress.done}/{progress.total} tick
              </span>
            </div>
          )}
          <div className="flex flex-wrap justify-center gap-5">
            <div className="board-shell">
              <UgBoard state={s} meta={meta} instant />
            </div>
            <div className="flex w-[300px] flex-col gap-3.5">
              <Card>
                <CardHeader className="flex-row items-center gap-2">
                  <ClapperboardIcon className="size-4 text-indigo-600" />
                  <CardTitle className="text-base">回放控制</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Slider
                    min={0}
                    max={maxTick}
                    value={[idx]}
                    disabled={!loaded}
                    onValueChange={([v]) => { setPlaying(false); setIdx(v); }}
                  />
                  <div className="flex flex-wrap gap-1.5">
                    <Button
                      size="sm" variant="outline"
                      disabled={!loaded || idx === 0}
                      onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }}
                    >
                      <SkipBackIcon />
                    </Button>
                    <Button
                      size="sm"
                      disabled={!loaded || (idx >= maxTick && !playing)}
                      onClick={() => setPlaying((p) => !p)}
                    >
                      {playing ? <PauseIcon /> : <PlayIcon />}
                      {playing ? "暂停" : "播放"}
                    </Button>
                    <Button
                      size="sm" variant="outline"
                      disabled={!loaded || idx >= maxTick}
                      onClick={() => { setPlaying(false); setIdx((i) => Math.min(maxTick, i + 1)); }}
                    >
                      <SkipForwardIcon />
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-1">
                    {[0.5, 1, 2, 4].map((v) => (
                      <Button
                        key={v}
                        size="sm"
                        variant={speed === v ? "default" : "ghost"}
                        className="px-2"
                        onClick={() => setSpeed(v)}
                      >
                        {v}x
                      </Button>
                    ))}
                    <span className="ml-auto text-xs text-muted-foreground">
                      tick {idx} / {maxTick}
                    </span>
                  </div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex-row items-center gap-2">
                  <SwordsIcon className="size-4 text-indigo-600" />
                  <CardTitle className="text-base">对局信息</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Stat label="TICK" value={s ? s.tick : 0} />
                  {s && s.score != null && <Stat label="得分" value={s.score} />}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
