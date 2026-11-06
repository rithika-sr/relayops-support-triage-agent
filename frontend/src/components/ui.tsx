"use client";

// Reusable UI primitives. Native elements with accessible labels and visible focus states.

import Link from "next/link";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { ApiError } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger" | "amber";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-teal-700 text-white hover:bg-teal-600 border-teal-700",
  secondary: "bg-card text-text border-line-strong hover:bg-paper",
  ghost: "bg-transparent text-text border-transparent hover:bg-paper",
  danger: "bg-card text-danger-700 border-danger-700/40 hover:bg-danger-50",
  amber: "bg-amber-700 text-white border-amber-700 hover:bg-amber-700/90",
};

export function Button({
  variant = "secondary",
  busy,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
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
    <Link
      href={href}
      className={cx("inline-flex items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium", VARIANTS[variant], className)}
    >
      {children}
    </Link>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cx("rounded-lg border border-line bg-card", className)}>
      {title ? (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES = {
  neutral: "bg-paper text-muted border-line",
  teal: "bg-teal-50 text-teal-700 border-teal-100",
  amber: "bg-amber-50 text-amber-700 border-amber-100",
  danger: "bg-danger-50 text-danger-700 border-danger-700/20",
  ok: "bg-ok-50 text-ok-700 border-ok-700/20",
  ink: "bg-ink-900 text-white border-ink-900",
};
export type Tone = keyof typeof TONES;

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  open: "teal",
  pending_review: "amber",
  awaiting_review: "amber",
  pending_customer: "neutral",
  resolved: "ok",
  closed: "neutral",
  completed: "ok",
  succeeded: "ok",
  reconciled: "ok",
  passed: "ok",
  pass: "ok",
  approved: "ok",
  executed: "ok",
  running: "teal",
  queued: "neutral",
  executing: "teal",
  failed: "danger",
  fail: "danger",
  rejected: "danger",
  cancelled: "neutral",
  stale: "amber",
  warn: "amber",
  unknown: "amber",
  superseded: "neutral",
  investigating: "amber",
  monitoring: "teal",
  candidate: "amber",
  current: "ok",
  retired: "neutral",
  urgent: "danger",
  high: "amber",
  normal: "neutral",
  low: "neutral",
  unverified: "neutral",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge>—</Badge>;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status.replace(/_/g, " ")}</Badge>;
}

export function Field({ label, hint, error, children, id }: { label: string; hint?: string; error?: string; children: ReactNode; id: string }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error ? <p className="text-xs text-muted">{hint}</p> : null}
      {error ? (
        <p className="text-xs text-danger-700" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const INPUT = "w-full rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-sm placeholder:text-muted/70";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(INPUT, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(INPUT, "min-h-24", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(INPUT, "pr-8", props.className)} />;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 py-8 text-sm text-muted">
      <span className="size-4 animate-spin rounded-full border-2 border-teal-600 border-r-transparent" aria-hidden />
      {label}…
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong px-6 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  const title =
    e?.status === 401
      ? "Your session has ended"
      : e?.status === 403
        ? "You do not have access to this"
        : e?.status === 404
          ? "Not found"
          : e?.code === "model_unavailable"
            ? "The local model is unavailable"
            : "Something went wrong";
  return (
    <div role="alert" className="rounded-lg border border-danger-700/30 bg-danger-50 px-4 py-3 text-sm">
      <p className="font-medium text-danger-700">{title}</p>
      <p className="mt-0.5 text-danger-700/90">{e?.detail ?? (error instanceof Error ? error.message : String(error))}</p>
      {e?.status === 401 ? (
        <Link className="mt-2 inline-block font-medium text-teal-700 underline" href="/login">
          Sign in again
        </Link>
      ) : retry ? (
        <Button className="mt-2" onClick={retry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: Tone }) {
  return (
    <div className="rounded-lg border border-line bg-card px-4 py-3">
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", tone === "danger" && "text-danger-700", tone === "amber" && "text-amber-700")}>{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <code title={title} className="rounded bg-paper px-1 py-0.5 font-mono text-xs">
      {children}
    </code>
  );
}

export function Notice({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <div className={cx("rounded-md border px-3 py-2 text-sm", TONES[tone])}>{children}</div>;
}
