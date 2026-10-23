import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Copy, X } from "lucide-react";

export function btnClass(variant = "outline", size = "", extra = "") {
  const parts = ["lab-btn", `lab-btn--${variant}`];
  if (size) parts.push(`lab-btn--${size}`);
  if (extra) parts.push(extra);
  return parts.filter(Boolean).join(" ");
}

export function Button({
  variant = "outline",
  size = "",
  block = false,
  className = "",
  type = "button",
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      className={btnClass(variant, size, `${block ? "lab-btn--block" : ""} ${className}`)}
      {...rest}
    >
      {children}
    </button>
  );
}

export function LinkButton({ variant = "outline", size = "", block = false, className = "", children, ...rest }) {
  return (
    <a className={btnClass(variant, size, `${block ? "lab-btn--block" : ""} ${className}`)} {...rest}>
      {children}
    </a>
  );
}

export function IconButton({ className = "", bare = false, children, ...rest }) {
  return (
    <button
      type="button"
      className={`lab-icon-btn${bare ? " lab-icon-btn--bare" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Pill({ tone = "neutral", dot = false, children, className = "" }) {
  return (
    <span className={`lab-pill lab-pill--${tone} ${className}`}>
      {dot ? <i className="lab-pill__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function Chip({ children, className = "" }) {
  return <span className={`lab-chip ${className}`}>{children}</span>;
}

export function Card({ className = "", flush = false, as: Tag = "div", children, ...rest }) {
  return (
    <Tag className={`lab-card${flush ? " lab-card--flush" : ""} ${className}`} {...rest}>
      {children}
    </Tag>
  );
}

export function SectionHead({ title, mono, action, className = "" }) {
  return (
    <div className={`lab-sec-head ${className}`}>
      <h2 className="lab-sec-title">
        {title}
        {mono ? <span className="lab-mono">{mono}</span> : null}
      </h2>
      {action}
    </div>
  );
}

export function Track({ value = 0, className = "", small = false }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className={`lab-track${small ? " lab-track--sm" : ""} ${className}`}>
      <div className="lab-track__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function EmptyState({ icon, title, desc, action, className = "" }) {
  return (
    <div className={`lab-empty ${className}`}>
      {icon ? <div className="lab-empty__icon">{icon}</div> : null}
      {title ? <div className="lab-empty__title">{title}</div> : null}
      {desc ? <p className="lab-empty__desc">{desc}</p> : null}
      {action}
    </div>
  );
}

export function Loading({ label = "载入中", className = "" }) {
  return (
    <div className={`lab-loading ${className}`}>
      <span className="lab-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null;
  const message = error.message || String(error);
  return (
    <div className="lab-error" role="alert">
      <span className="lab-grow">{message}</span>
      {onRetry ? (
        <Button size="xs" variant="ghost" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  );
}

export function Tabs({ items, value, onChange, className = "" }) {
  return (
    <div className={`envp-tabs ${className}`} role="tablist">
      {items.map((item) => {
        const key = typeof item === "string" ? item : item.key;
        const label = typeof item === "string" ? item : item.label;
        const active = key === value;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active}
            className={`envp-tab${active ? " is-active" : ""}`}
            onClick={() => onChange(key)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function CopyButton({ text, className = "", label = "" }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => timer.current && clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 1400);
    } catch (e) {
      /* clipboard unavailable */
    }
  };
  return (
    <button type="button" className={`lab-icon-btn lab-icon-btn--bare ${className}`} onClick={copy} title="复制">
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {label ? <span className="lab-mono">{copied ? "已复制" : label}</span> : null}
    </button>
  );
}

export function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="lab-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`lab-modal${wide ? " lab-modal--wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="lab-modal__head">
          <div className="lab-modal__title">{title}</div>
          <button type="button" className="lab-icon-btn lab-icon-btn--bare" onClick={onClose} aria-label="关闭">
            <X size={15} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label className="lab-field">
      <span>{label}</span>
      {children}
      {hint ? <span className="lab-mono" style={{ letterSpacing: 0 }}>{hint}</span> : null}
    </label>
  );
}

export { ArrowRight };
