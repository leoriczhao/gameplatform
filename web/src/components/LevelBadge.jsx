import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext.jsx";
import { getJson } from "../api.js";
import { Badge } from "./ui/badge.jsx";
import { Progress } from "./ui/progress.jsx";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip.jsx";

/* 顶栏等级徽章：LV + 到下一级的 XP 进度条（数值见 docs/design/08） */
export default function LevelBadge({ compact = false }) {
  const { user, token } = useAuth();
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    if (!user || !token) return undefined;
    getJson("/api/v1/profile", token)
      .then((d) => setProfile(d.profile))
      .catch(() => {});
  }, [user, token]);

  if (!profile) return null;
  const need = 100 * profile.level;  // xp span to the next level (50·(n+1)n - 50n(n-1))
  const pct = Math.round(profile.level_progress * 100);
  const tip = `经验 ${profile.xp} XP · 距离 ${profile.level + 1} 级还差 ${Math.max(0, Math.round((1 - profile.level_progress) * need))} XP`;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-default items-center gap-2">
          <Badge className="border-indigo-500/40 bg-indigo-500/10 font-bold text-indigo-600">
            LV {profile.level}
          </Badge>
          {!compact && <Progress value={pct} className="w-20" />}
          {compact && <span className="text-xs text-muted-foreground">{profile.xp} XP</span>}
        </span>
      </TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}
