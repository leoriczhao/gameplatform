import * as React from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { cn } from "../../lib/utils.js";

/* Client-side paging helper. Usage:
   const paged = usePaged(rows, 15);
   ... paged.items.map(...)
   <Pagination page={paged.page} pageCount={paged.pageCount} total={paged.total}
               onChange={paged.setPage} /> */
function usePaged(items, pageSize = 15) {
  const [page, setPage] = React.useState(1);
  const pageCount = Math.max(1, Math.ceil((items?.length || 0) / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  return {
    items: (items || []).slice(start, start + pageSize),
    page: safePage,
    pageCount,
    total: items?.length || 0,
    setPage: (p) => setPage(Math.min(Math.max(1, p), pageCount)),
  };
}

function Pagination({ page, pageCount, total, onChange, className }) {
  if (pageCount <= 1) return null;
  const pages = [];
  for (let p = 1; p <= pageCount; p++) {
    if (p === 1 || p === pageCount || Math.abs(p - page) <= 1) pages.push(p);
    else if (pages[pages.length - 1] !== "…") pages.push("…");
  }
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-2 pt-3", className)}>
      <span className="text-xs text-muted-foreground">
        共 {total} 条 · 第 {page} / {pageCount} 页
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="flex size-7 cursor-pointer items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-neutral-100 hover:text-foreground disabled:cursor-default disabled:opacity-40"
          aria-label="上一页"
        >
          <ChevronLeftIcon className="size-3.5" />
        </button>
        {pages.map((p, i) => (
          p === "…" ? (
            <span key={`e${i}`} className="px-1 text-xs text-muted-foreground">…</span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onChange(p)}
              className={cn(
                "size-7 cursor-pointer rounded-md text-xs transition-colors",
                p === page
                  ? "bg-primary font-semibold text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-neutral-100 hover:text-foreground"
              )}
            >
              {p}
            </button>
          )
        ))}
        <button
          type="button"
          disabled={page >= pageCount}
          onClick={() => onChange(page + 1)}
          className="flex size-7 cursor-pointer items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-neutral-100 hover:text-foreground disabled:cursor-default disabled:opacity-40"
          aria-label="下一页"
        >
          <ChevronRightIcon className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

export { Pagination, usePaged };
