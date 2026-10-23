import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { EmptyState } from "../ui.jsx";

export default function LabNotFound() {
  return (
    <div className="lab-card">
      <EmptyState
        icon={<Compass size={16} />}
        title="页面不存在（404）"
        desc="该链接已失效或已移除（如旧的对战中心入口）。新的信息架构里，玩与 PvP 入口都在各环境的详情页。"
        action={
          <Link className="lab-btn lab-btn--primary lab-btn--sm" to="/">
            回到总览
          </Link>
        }
      />
    </div>
  );
}
