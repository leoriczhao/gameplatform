/* 复合动作构建器（docs/design/17 §7.3）：pvp.action=unit，每 tick 每单位一条指令。
   在棋盘上点自己的单位选中，选指令与方向后加入"本 tick 待提交"列表，最后整体提交。

   指令表来自 microrts 的 adapter.info()（平台目前只有这一个复合动作游戏）；
   UGC 若以后声明了动作表，可以在 meta 里补充，前端优先读 meta.pvp.commands。 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { MousePointer2, Send, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../lab/ui.jsx";

const DEFAULT_COMMANDS = [
  { id: 0, key: "W", label: "等待" },
  { id: 1, key: "M", label: "移动" },
  { id: 2, key: "H", label: "采矿" },
  { id: 3, key: "R", label: "返回" },
  { id: 4, key: "B", label: "建造" },
  { id: 5, key: "P", label: "生产" },
  { id: 6, key: "A", label: "攻击" },
];
const DIRECTIONS = [{ id: 0, label: "N" }, { id: 1, label: "E" }, { id: 2, label: "S" }, { id: 3, label: "W" }];
const UNIT_TYPES = ["worker", "light", "heavy", "ranged", "barracks", "base"];
const DIR_REQUIRED = new Set([1, 2, 3, 4, 5, 6]);   // 等待不需要方向
const TYPE_REQUIRED = new Set([4, 5]);

function seatOwner(seat) {
  if (seat === "p0") return 0;
  if (seat === "p1") return 1;
  return null;
}

export default function CompositeBuilder({ view, meta, caps, onAction, onBoardHandler }) {
  const commands = (Array.isArray(meta?.pvp?.commands) && meta.pvp.commands.length)
    ? meta.pvp.commands : DEFAULT_COMMANDS;
  const mySeat = view?.you?.seat ?? null;
  const myOwner = seatOwner(mySeat);
  const units = view?.frame?.units || [];

  const [selUnit, setSelUnit] = useState(null);
  const [cmd, setCmd] = useState(null);
  const [dir, setDir] = useState(0);
  const [unitType, setUnitType] = useState("worker");
  const [pending, setPending] = useState([]);
  const [busy, setBusy] = useState(false);

  const selectedUnit = useMemo(
    () => (selUnit == null ? null : units.find((unit) => unit.id === selUnit) || null),
    [selUnit, units],
  );

  /* 棋盘点击：只有己方单位可以被选中。 */
  useEffect(() => {
    if (!onBoardHandler) return undefined;
    if (!caps.canAct || myOwner == null) {
      onBoardHandler(null);
      return undefined;
    }
    onBoardHandler((x, y) => {
      const hit = units.find((unit) => unit.x === x && unit.y === y);
      if (hit && hit.owner === myOwner) {
        setSelUnit(hit.id);
        setCmd(null);
      } else if (hit) {
        toast.info("这是对手单位");
      }
    });
    return () => onBoardHandler(null);
  }, [onBoardHandler, caps.canAct, myOwner, units]);

  useEffect(() => { setSelUnit(null); }, [view?.tick]);
  useEffect(() => { if (!caps.canAct) { setPending([]); setCmd(null); } }, [caps.canAct]);

  const add = useCallback(() => {
    if (selUnit == null) { toast.warning("先在棋盘上点选己方单位"); return; }
    if (cmd == null) { toast.warning("选择一条指令"); return; }
    const entry = [selUnit, cmd];
    if (DIR_REQUIRED.has(cmd)) entry.push(dir);
    if (TYPE_REQUIRED.has(cmd)) entry.push(unitType);
    setPending((items) => [...items, entry]);
    setSelUnit(null);
    setCmd(null);
  }, [selUnit, cmd, dir, unitType]);

  useEffect(() => {
    if (!caps.canAct) return undefined;
    const onKey = (event) => {
      const hit = commands.find((item) => item.key === event.key.toUpperCase());
      if (hit) { event.preventDefault(); setCmd(hit.id); return; }
      if (event.key === "Enter" && (selUnit != null || pending.length)) {
        event.preventDefault();
        if (selUnit != null) add();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [caps.canAct, commands, selUnit, pending.length, add]);

  const submit = async () => {
    if (!caps.canAct || busy) return;
    setBusy(true);
    try {
      await onAction(pending, "复合指令");
      setPending([]);
      setSelUnit(null);
      setCmd(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stage-controls stage-controls--composite">
      <div className="stage-controls__row">
        <span className="stage-controls__label"><MousePointer2 size={12} /> 指令</span>
        <div className="stage-commands">
          {commands.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`stage-cmd${cmd === item.id ? " is-active" : ""}`}
              disabled={!caps.canAct}
              onClick={() => setCmd(item.id)}
              title={item.key}
            >
              <kbd>{item.key}</kbd> {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className="stage-controls__row">
        <span className="stage-controls__label">方向 / 类型</span>
        <div className="stage-choices">
          {DIRECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`stage-cmd${dir === item.id ? " is-active" : ""}`}
              disabled={!caps.canAct}
              onClick={() => setDir(item.id)}
            >
              {item.label}
            </button>
          ))}
          {cmd != null && TYPE_REQUIRED.has(cmd) ? (
            <select
              className="lab-select stage-select"
              value={unitType}
              disabled={!caps.canAct}
              onChange={(event) => setUnitType(event.target.value)}
            >
              {UNIT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
          ) : null}
          <Button size="xs" variant="outline" disabled={!caps.canAct} onClick={add}>加入待提交</Button>
        </div>
        <span className="stage-grow" />
        <Button variant="primary" size="sm" disabled={!caps.canAct || busy} onClick={submit}>
          <Send size={12} /> 提交本 tick
        </Button>
      </div>
      <div className="stage-controls__row stage-controls__row--wrap">
        {selectedUnit ? (
          <span className="stage-note">
            已选 #{selectedUnit.id} {selectedUnit.type} @ ({selectedUnit.x},{selectedUnit.y})
          </span>
        ) : (
          <span className="stage-note">点棋盘上的己方单位选中；空列表也可以提交。</span>
        )}
        {pending.length ? (
          <div className="stage-pending">
            {pending.map((entry, index) => {
              const command = commands.find((item) => item.id === entry[1]);
              return (
                <button
                  key={`${entry.join("-")}-${index}`}
                  type="button"
                  className="stage-pending__chip"
                  title="点击移除"
                  onClick={() => setPending((items) => items.filter((_, i) => i !== index))}
                >
                  #{entry[0]} {command ? command.label : entry[1]}
                  {DIRECTIONS[entry[2]] ? " " + DIRECTIONS[entry[2]].label : ""}
                  {entry[3] ? " " + entry[3] : ""} <X size={10} />
                </button>
              );
            })}
          </div>
        ) : null}
        <span className="stage-grow" />
        <span className="stage-note">{caps.canAct ? "快捷键 M/H/R/B/P/A/W 选指令" : (caps.readOnlyReason || "只读")}</span>
      </div>
    </div>
  );
}
