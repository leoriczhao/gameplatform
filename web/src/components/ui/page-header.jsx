import * as React from "react";
import { cn } from "../../lib/utils.js";

/* Consistent page heading: plain icon + ink title + optional description/actions. */
function PageHeader({ icon: Icon, title, description, actions, className, ...props }) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-start justify-between gap-4", className)} {...props}>
      <div className="flex items-start gap-3">
        {Icon ? (
          <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-700 shadow-sm">
            <Icon className="size-5" />
          </div>
        ) : null}
        <div>
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
            <span className="gradient-text">{title}</span>
          </h1>
          {description ? (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export { PageHeader };
