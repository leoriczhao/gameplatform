import * as React from "react";
import { cn } from "../../lib/utils.js";

function Table({ className, ...props }) {
  return (
    <div data-slot="table-container" className="relative w-full overflow-x-auto">
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b [&_tr]:border-neutral-200", className)}
      {...props}
    />
  );
}

function TableBody({ className, ...props }) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-neutral-100 transition-colors hover:bg-neutral-50 data-[state=selected]:bg-primary/5",
        className
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 px-3 text-left align-middle text-xs font-medium tracking-wide text-muted-foreground uppercase [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }) {
  return (
    <td
      data-slot="table-cell"
      className={cn("px-3 py-2.5 align-middle [&:has([role=checkbox])]:pr-0", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableHead, TableRow, TableCell };
