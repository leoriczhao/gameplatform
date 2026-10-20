import * as React from "react";
import { InboxIcon } from "lucide-react";
import { cn } from "../../lib/utils.js";

function EmptyState({ className, icon: Icon = InboxIcon, title, description, children, ...props }) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 py-12 text-center",
        className
      )}
      {...props}
    >
      <div className="flex size-12 items-center justify-center rounded-full bg-neutral-100">
        <Icon className="size-6 text-neutral-400" />
      </div>
      <div className="text-sm font-medium text-neutral-700">{title || "暂无数据"}</div>
      {description ? <div className="max-w-sm text-xs text-muted-foreground">{description}</div> : null}
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  );
}

export { EmptyState };
