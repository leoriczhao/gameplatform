import {
  Gamepad2Icon, SwordsIcon, ZapIcon, BlocksIcon,
} from "lucide-react";
import { cn } from "../lib/utils.js";

/* 通用游戏选择磁贴条（13 G5+ 交互重构）：横向滚动，替代单个下拉框。
   游戏数量多时横向滑动即可；选中态高亮。BGA/Lichess 等对战平台均用
   「游戏磁贴/标签」而非下拉框做游戏切换。 */

export const GAME_ICONS = {
  microrts: SwordsIcon,
  snake: ZapIcon,
  tetris: BlocksIcon,
};

export default function GameStrip({ games, value, onChange, className }) {
  if (!games.length) return null;
  return (
    <div className={cn("flex gap-2 overflow-x-auto pb-1", className)}>
      {games.map((g) => {
        const Icon = GAME_ICONS[g.id] || Gamepad2Icon;
        const active = g.id === value;
        return (
          <button
            key={g.id}
            type="button"
            onClick={() => onChange(g.id)}
            title={g.description || g.name}
            className={cn(
              "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors",
              active
                ? "border-indigo-600 bg-indigo-600 text-white shadow-sm"
                : "border-border bg-card text-foreground hover:bg-muted"
            )}
          >
            <Icon className="size-4" />
            {g.name}
          </button>
        );
      })}
    </div>
  );
}