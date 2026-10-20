import * as React from "react";
import { Loader2Icon } from "lucide-react";
import { cn } from "../../lib/utils.js";

function Spinner({ className, size = "default", text, ...props }) {
  const s = { sm: "size-4", default: "size-6", lg: "size-8" }[size];
  return (
    <div
      role="status"
      className={cn("flex flex-col items-center justify-center gap-2 py-8 text-muted-foreground", className)}
      {...props}
    >
      <Loader2Icon className={cn("animate-spin text-primary", s)} />
      {text ? <span className="text-sm">{text}</span> : null}
    </div>
  );
}

export { Spinner };
