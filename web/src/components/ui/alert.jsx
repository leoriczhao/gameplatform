import * as React from "react";
import { cva } from "class-variance-authority";
import { AlertTriangleIcon, InfoIcon, CircleAlertIcon, CircleCheckIcon } from "lucide-react";
import { cn } from "../../lib/utils.js";

const alertVariants = cva(
  "relative flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-sm [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-neutral-200 bg-neutral-50 text-foreground [&>svg]:text-neutral-500",
        info: "border-sky-200 bg-sky-50 text-sky-800 [&>svg]:text-sky-600",
        success: "border-emerald-200 bg-emerald-50 text-emerald-800 [&>svg]:text-emerald-600",
        warning: "border-amber-200 bg-amber-50 text-amber-800 [&>svg]:text-amber-600",
        destructive: "border-red-200 bg-red-50 text-red-800 [&>svg]:text-red-600",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

const ICONS = {
  default: InfoIcon,
  info: InfoIcon,
  success: CircleCheckIcon,
  warning: AlertTriangleIcon,
  destructive: CircleAlertIcon,
};

function Alert({ className, variant, ...props }) {
  const Icon = ICONS[variant] || InfoIcon;
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props}>
    <Icon />
    <div className="min-w-0 flex-1">{props.children}</div>
  </div>;
}

function AlertTitle({ className, ...props }) {
  return (
    <div className={cn("mb-0.5 font-semibold leading-none tracking-tight", className)} {...props} />
  );
}

function AlertDescription({ className, ...props }) {
  return (
    <div className={cn("text-sm opacity-90 [&_p]:leading-relaxed", className)} {...props} />
  );
}

export { Alert, AlertTitle, AlertDescription };
