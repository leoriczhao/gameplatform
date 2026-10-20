import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils.js";

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium transition-colors [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "border-transparent bg-indigo-50 text-indigo-700",
        secondary: "border-transparent bg-neutral-100 text-neutral-700",
        destructive: "border-transparent bg-red-50 text-red-700",
        success: "border-transparent bg-emerald-50 text-emerald-700",
        warning: "border-transparent bg-amber-50 text-amber-700",
        info: "border-transparent bg-sky-50 text-sky-700",
        outline: "border-neutral-200 bg-transparent text-neutral-600",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

function Badge({ className, variant, ...props }) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
