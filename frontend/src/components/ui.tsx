"use client";

// Shared UI primitives. Native elements with accessible names, visible focus, and color-independent status.

import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { ApiError } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger" | "warn";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-600 text-white border-accent-600 hover:bg-accent-700 shadow-[var(--shadow-raised)]",
  secondary: "bg-card text-text border-line-strong hover:bg-sunken",
  ghost: "bg-transparent text-muted border-transparent hover:bg-sunken hover:text-text",
  danger: "bg-card text-danger-700 border-line-strong hover:bg-danger-50",
  warn: "bg-warn-700 text-white border-warn-700 hover:opacity-90",
};

export function Button({
  variant = "secondary",
  size = "md",
  busy,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors",
        size === "sm" ? "px-2.5 py-1 text-[13px]" : "px-3.5 py-2 text-sm",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
    >
      {busy ? <span className="size-3 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "secondary", className }: { href: string; children: ReactNode; variant?: Variant; className?: string }) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center gap-2 rounded-md border px-3.5 py-2 text-sm font-medium", VARIANTS[variant], className)}>
      {children}
    </Link>
  );
}

export function Card({ children, className, title, actions, padded = true }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; padded?: boolean }) {
  return (
    <section className={cx("min-w-0 rounded-xl border border-line bg-card shadow-[var(--shadow-raised)]", className)}>
      {title ? (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className={padded ? "p-5" : undefined}>{children}</div>
    </section>
  );
}

const TONES = {
  neutral: { box: "bg-sunken text-ink-700", dot: "bg-subtle" },
  accent: { box: "bg-accent-50 text-accent-700", dot: "bg-accent-600" },
  warn: { box: "bg-warn-50 text-warn-700", dot: "bg-warn-700" },
  danger: { box: "bg-danger-50 text-danger-700", dot: "bg-danger-700" },
  ok: { box: "bg-ok-50 text-ok-700", dot: "bg-ok-700" },
  info: { box: "bg-info-50 text-info-700", dot: "bg-info-700" },
  ink: { box: "bg-ink-800 text-white", dot: "bg-white" },
};
export type Tone = keyof typeof TONES;

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", TONES[tone].box)}>
      {children}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label?: string }> = {
  open: { tone: "accent" },
  pending_review: { tone: "warn", label: "needs review" },
  awaiting_review: { tone: "warn", label: "awaiting review" },
  pending_customer: { tone: "neutral", label: "waiting on customer" },
  resolved: { tone: "ok" },
  closed: { tone: "neutral" },
  completed: { tone: "ok" },
  succeeded: { tone: "ok" },
  reconciled: { tone: "ok" },
  passed: { tone: "ok" },
  pass: { tone: "ok", label: "passed" },
  approved: { tone: "ok" },
  executed: { tone: "ok", label: "published" },
  running: { tone: "accent" },
  queued: { tone: "neutral" },
  executing: { tone: "accent", label: "publishing" },
  failed: { tone: "danger" },
  fail: { tone: "danger", label: "failed" },
  rejected: { tone: "danger" },
  cancelled: { tone: "neutral" },
  stale: { tone: "warn" },
  warn: { tone: "warn", label: "check" },
  unknown: { tone: "warn" },
  superseded: { tone: "neutral" },
  investigating: { tone: "warn" },
  monitoring: { tone: "accent" },
  candidate: { tone: "warn" },
  current: { tone: "ok" },
  retired: { tone: "neutral" },
  urgent: { tone: "danger" },
  high: { tone: "warn" },
  normal: { tone: "neutral" },
  low: { tone: "neutral" },
  unverified: { tone: "neutral" },
  healthy: { tone: "ok" },
  degraded: { tone: "warn" },
  configured: { tone: "neutral" },
  disconnected: { tone: "neutral" },
  accepted: { tone: "ok" },
  duplicate: { tone: "neutral" },
};

/** Status shown as a dot plus a word, so it never depends on color alone. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge>—</Badge>;
  const s = STATUS[status] ?? { tone: "neutral" as Tone };
  return (
    <Badge tone={s.tone}>
      <span className={cx("size-1.5 rounded-full", TONES[s.tone].dot)} aria-hidden />
      {s.label ?? status.replace(/_/g, " ")}
    </Badge>
  );
}

export function Field({ label, hint, error, children, id }: { label: string; hint?: string; error?: string; children: ReactNode; id: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      {children}
      {hint && !error ? <p className="text-[13px] text-muted">{hint}</p> : null}
      {error ? <p className="text-[13px] text-danger-700" role="alert">{error}</p> : null}
    </div>
  );
}

const INPUT = "w-full rounded-md border border-line-strong bg-white px-3 py-2 text-sm placeholder:text-subtle shadow-[0_1px_1px_rgb(16_24_40/0.04)]";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(INPUT, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(INPUT, "min-h-24", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(INPUT, "pr-8", props.className)} />;
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2 text-[13px] text-muted">
      <ol className="flex flex-wrap items-center gap-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-1.5">
            {it.href ? <Link className="hover:text-text" href={it.href}>{it.label}</Link> : <span aria-current="page">{it.label}</span>}
            {i < items.length - 1 ? <span aria-hidden>/</span> : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({ title, subtitle, actions, crumbs }: { title: string; subtitle?: ReactNode; actions?: ReactNode; crumbs?: { label: string; href?: string }[] }) {
  return (
    <div className="mb-6">
      {crumbs ? <Breadcrumbs items={crumbs} /> : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle ? <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="mb-4 flex flex-wrap items-center gap-2">{children}</div>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div role="status" aria-live="polite" aria-label="Loading" className="flex flex-col gap-2.5 py-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-sunken" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 py-8 text-sm text-muted">
      <span className="size-4 animate-spin rounded-full border-2 border-accent-600 border-r-transparent" aria-hidden />
      {label}…
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-card px-6 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  const title =
    e?.status === 401 ? "Your session has ended"
      : e?.status === 403 ? "You do not have access to this"
        : e?.status === 404 ? "Not found"
          : e?.code === "model_unavailable" ? "The local model is unavailable"
            : "Something went wrong";
  return (
    <div role="alert" className="rounded-xl border border-danger-700/25 bg-danger-50 px-4 py-3 text-sm">
      <p className="font-medium text-danger-700">{title}</p>
      <p className="mt-0.5 text-danger-700/90">{e?.detail ?? (error instanceof Error ? error.message : String(error))}</p>
      {e?.status === 401 ? (
        <Link className="mt-2 inline-block font-medium text-accent-700 underline" href="/login">Sign in again</Link>
      ) : retry ? (
        <Button className="mt-2" size="sm" onClick={retry}>Retry</Button>
      ) : null}
    </div>
  );
}

export function Stat({ label, value, hint, tone, href }: { label: string; value: ReactNode; hint?: string; tone?: Tone; href?: string }) {
  const body = (
    <>
      <p className="text-[13px] font-medium text-muted">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", tone === "danger" && "text-danger-700", tone === "warn" && "text-warn-700")}>{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
    </>
  );
  const cls = "block rounded-xl border border-line bg-card px-4 py-3 shadow-[var(--shadow-raised)]";
  return href ? <Link href={href} className={cx(cls, "hover:border-accent-600")}>{body}</Link> : <div className={cls}>{body}</div>;
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return <code title={title} className="rounded bg-sunken px-1 py-0.5 font-mono text-xs break-all">{children}</code>;
}

export function Notice({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <div className={cx("rounded-lg px-3.5 py-2.5 text-sm", TONES[tone].box)}>
      {title ? <p className="font-medium">{title}</p> : null}
      <div>{children}</div>
    </div>
  );
}

/** Accessible tabs: arrow keys move between tabs; panels are labelled by their tab. */
export function Tabs({ tabs, value, onChange, label }: { tabs: { id: string; label: ReactNode; count?: number }[]; value: string; onChange: (id: string) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    const next = (i + delta + tabs.length) % tabs.length;
    refs.current[next]?.focus();
    onChange(tabs[next].id);
  };
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => { refs.current[i] = el; }}
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={value === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={value === t.id ? 0 : -1}
          onKeyDown={(e) => onKey(e, i)}
          onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap", value === t.id ? "border-accent-600 font-medium text-text" : "border-transparent text-muted hover:text-text")}
        >
          {t.label}{t.count !== undefined ? <span className="ml-1.5 rounded-full bg-sunken px-1.5 text-xs text-muted">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} className="pt-4">{children}</div>;
}

/** Side sheet dialog: Esc closes, focus moves in and returns to the opener. */
export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="presentation">
      <div className="absolute inset-0 bg-ink-900/30" onClick={onClose} aria-hidden />
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={id}
        className="relative flex h-full w-full max-w-xl flex-col bg-card shadow-[var(--shadow-overlay)] outline-none">
        <header className="flex items-center justify-between border-b border-line px-5 py-3">
          <h2 id={id} className="font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">Close</Button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

type Toast = { id: number; text: string; tone: Tone };
const ToastCtx = createContext<(text: string, tone?: Tone) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed right-4 bottom-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status" className={cx("rounded-lg px-4 py-2.5 text-sm shadow-[var(--shadow-overlay)]", TONES[t.tone].box)}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

/** Collapsible section built on a native <details> element. */
export function Disclosure({ summary, children, defaultOpen }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="group rounded-lg border border-line bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-2.5 text-sm font-medium">
        <span>{summary}</span>
        <span aria-hidden className="text-muted transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="border-t border-line px-4 py-3">{children}</div>
    </details>
  );
}
