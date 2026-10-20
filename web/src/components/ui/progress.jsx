import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "../../lib/utils.js";

function Progress({ className, value, indicatorClassName, ...props }) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-neutral-200", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={cn(
          "h-full w-full flex-1 rounded-full bg-primary transition-all",
          indicatorClassName
        )}
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress };
