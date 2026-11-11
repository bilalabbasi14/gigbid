"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({ variant = "secondary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-white hover:opacity-90 border-transparent",
    secondary: "bg-surface text-foreground border-border hover:bg-background",
    danger: "bg-rose-600 text-white hover:bg-rose-700 border-transparent",
    ghost: "bg-transparent text-foreground border-transparent hover:bg-background",
  };
  return (
    <button
      type="button"
      {...props}
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", styles[variant], className)}
    />
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-border bg-surface p-4", className)}>
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-6 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-accent" aria-hidden />
      {label}…
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100">
      <p className="font-medium">{msg}</p>
      {onRetry && (
        <Button className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

const TONES = {
  green: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  amber: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  red: "bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200",
  blue: "bg-indigo-100 text-indigo-900 dark:bg-indigo-950 dark:text-indigo-200",
  gray: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
} as const;
export type Tone = keyof typeof TONES;

export function Pill({ tone = "gray", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone])}>
      {children}
    </span>
  );
}

export function RiskBadge({ score, flags = [] }: { score?: number | null; flags?: string[] }) {
  if (score === null || score === undefined) return <Pill>risk n/a</Pill>;
  const tone: Tone = score >= 0.7 ? "red" : score >= 0.4 ? "amber" : "green";
  const label = score >= 0.7 ? "high risk" : score >= 0.4 ? "some risk" : "low risk";
  return (
    <Pill tone={tone} title={flags.join(", ") || undefined}>
      {label} {Math.round(score * 100)}
    </Pill>
  );
}

export function DecisionPill({ decision }: { decision?: string | null }) {
  if (!decision) return <Pill>not analysed</Pill>;
  const tone: Tone = decision === "bid" ? "green" : decision === "watch" ? "amber" : "gray";
  return <Pill tone={tone}>{decision}</Pill>;
}

export function StatusPill({ status }: { status: string }) {
  const tone: Tone =
    status === "submitted" ? "green" : status === "awaiting_approval" || status === "drafted" ? "blue" : status === "needs_attention" || status === "failed" || status === "blocked" ? "red" : status === "running" || status === "analysing" || status === "queued" ? "amber" : "gray";
  return <Pill tone={tone}>{status.replaceAll("_", " ")}</Pill>;
}

export function Meter({ value, label }: { value?: number | null; label: string }) {
  const v = value ?? 0;
  const color = v >= 0.6 ? "bg-emerald-500" : v >= 0.45 ? "bg-amber-500" : "bg-zinc-400";
  return (
    <div className="flex items-center gap-2" aria-label={`${label} ${value === null || value === undefined ? "not available" : Math.round(v * 100) + "%"}`}>
      <div className="h-1.5 w-20 overflow-hidden rounded bg-border">
        <div className={cx("h-full", color)} style={{ width: `${Math.round(v * 100)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted">{value === null || value === undefined ? "n/a" : Math.round(v * 100)}</span>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm placeholder:text-muted";
