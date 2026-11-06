/* StageBoard（docs/design/17 §7.3）：深色井贴合棋盘，按格放大到 [12, 56]px。
   把计算出的 cell 大小注入 meta.board.cell.size，复用 UgBoard/BoardCanvas 的
   DPR 重新栅格化（不再用 BoardFrame 的 CSS transform，放大后依然清晰）。 */

import { useEffect, useMemo, useRef, useState } from "react";
import UgBoard from "../../components/UgBoard.jsx";

const MIN_CELL = 12;
const MAX_CELL = 56;
const WELL_PADDING = 14;

function boardDims(meta) {
  const board = meta?.board || {};
  return { width: Number(board.width) || 12, height: Number(board.height) || 8 };
}

export default function StageBoard({ meta, frame, onCellClick, overlay, interactive = false }) {
  const wellRef = useRef(null);
  const [cell, setCell] = useState(24);
  const { width, height } = boardDims(meta);
  const hasBoard = Boolean(meta?.board && width > 0 && height > 0);

  useEffect(() => {
    const well = wellRef.current;
    if (!well || !hasBoard) return undefined;
    const fit = () => {
      const availW = Math.max(0, well.clientWidth - WELL_PADDING * 2);
      const availH = Math.max(0, (well.clientHeight || window.innerHeight * 0.6) - WELL_PADDING * 2);
      const byWidth = availW / width;
      const byHeight = availH / height;
      const next = Math.floor(Math.min(byWidth, byHeight));
      if (next > 0) setCell(Math.max(MIN_CELL, Math.min(MAX_CELL, next)));
    };
    fit();
    const raf = requestAnimationFrame(fit);
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(fit) : null;
    observer?.observe(well);
    window.addEventListener("resize", fit);
    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [hasBoard, width, height]);

  /* 覆盖游戏包声明的固定格子尺寸，让舞台按井大小放大。 */
  const stageMeta = useMemo(() => {
    if (!meta) return meta;
    const board = meta.board || {};
    return { ...meta, board: { ...board, cell: { ...(board.cell || {}), size: cell } } };
  }, [meta, cell]);

  return (
    <div className="stage-board" ref={wellRef}>
      <div className="stage-board__ink">
        {hasBoard && frame ? (
          <UgBoard
            state={frame}
            meta={stageMeta}
            onCellClick={onCellClick || null}
            cellSize={cell}
            interactive={interactive || Boolean(onCellClick)}
          />
        ) : (
          <div className="stage-board__empty">
            {hasBoard ? "等待第一帧…" : "该游戏没有声明棋盘渲染（board）"}
          </div>
        )}
      </div>
      {overlay}
    </div>
  );
}
