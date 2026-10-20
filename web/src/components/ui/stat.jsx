import * as React from "react";
import { cn } from "../../lib/utils.js";

/* Small labeled metric — replaces antd Statistic. */
function Stat({ label, value, suffix, className, valueClassName, ...props }) {
  return (
    <div className={cn("flex flex-col gap-1", className)} {...props}>
      <span className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
        {label}
      </span>
      <span className={cn("text-2xl leading-none font-bold tabular-nums", valueClassName)}>
        {value}
        {suffix ? <span className="ml-1 text-sm font-normal text-muted-foreground">{suffix}</span> : null}
      </span>
    </div>
  );
}

export { Stat };
