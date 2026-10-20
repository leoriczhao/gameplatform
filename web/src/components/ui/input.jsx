import * as React from "react";
import { cn } from "../../lib/utils.js";

function Input({ className, type, ...props }) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-9 w-full min-w-0 rounded-lg border border-input bg-card px-3 py-1 text-sm text-foreground shadow-sm transition-colors placeholder:text-muted-foreground/70 focus-visible:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50",
        "file:mr-3 file:h-full file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
        className
      )}
      {...props}
    />
  );
}

export { Input };
