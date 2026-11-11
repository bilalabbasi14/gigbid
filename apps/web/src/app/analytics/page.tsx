"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, ErrorState, PageHeader, Spinner } from "@/components/ui";
import { api, call, pct, type S } from "@/lib/client";

const FUNNEL = ["seen", "analysed", "bid", "submitted", "viewed", "replied", "interview", "hired"] as const;

export default function Analytics() {
  const q = useQuery<S["AnalyticsOut"]>({ queryKey: ["analytics"], queryFn: () => call(api.GET("/analytics")) });
  if (q.isLoading) return <Spinner label="Loading analytics" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const a = q.data!;
  const max = Math.max(1, ...FUNNEL.map((k) => a.funnel[k] ?? 0));
  const cl = a.cost_latency as Record<string, unknown>;
  const budget = (cl.budget ?? {}) as Record<string, number>;
  const retrieval = a.retrieval_results as Record<string, { overall?: Record<string, number> | null; n_jobs?: number }>;

  return (
    <div className="space-y-4">
      <PageHeader title="Analytics" subtitle="Outcomes, Connects economics and what every proposal cost to produce." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Funnel">
          <ul className="space-y-1.5" aria-label="Funnel">
            {FUNNEL.map((k) => (
              <li key={k} className="flex items-center gap-2 text-sm">
                <span className="w-20 capitalize text-muted">{k}</span>
                <span className="h-4 rounded bg-accent" style={{ width: `${Math.max(2, ((a.funnel[k] ?? 0) / max) * 100)}%` }} aria-hidden />
                <span className="tabular-nums">{a.funnel[k] ?? 0}</span>
              </li>
            ))}
            <li className="text-xs text-muted">Skipped {a.funnel.skipped ?? 0} · lost {a.funnel.lost ?? 0}</li>
          </ul>
        </Card>
        <Card title="Connects spent versus outcomes">
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-muted">Connects spent</dt>
            <dd className="tabular-nums">{String(a.connects.spent ?? 0)}</dd>
            <dt className="text-muted">Weekly budget</dt>
            <dd className="tabular-nums">{String(a.connects.weekly_budget ?? "n/a")}</dd>
            <dt className="text-muted">Replies</dt>
            <dd className="tabular-nums">{String(a.connects.replies ?? 0)}</dd>
            <dt className="text-muted">Connects per reply</dt>
            <dd className="tabular-nums">{String(a.connects.connects_per_reply ?? "n/a")}</dd>
            <dt className="text-muted">Hires</dt>
            <dd className="tabular-nums">{String(a.connects.hires ?? 0)}</dd>
          </dl>
        </Card>
        <Card title="Reply and hire rate by category">
          {a.by_category.length === 0 ? (
            <p className="text-sm text-muted">No submitted proposals yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th className="text-left">Category</th>
                  <th className="text-right">Sent</th>
                  <th className="text-right">Reply rate</th>
                  <th className="text-right">Hire rate</th>
                </tr>
              </thead>
              <tbody>
                {a.by_category.map((c) => (
                  <tr key={String(c.category)} className="border-t border-border">
                    <td>{String(c.category)}</td>
                    <td className="text-right tabular-nums">{String(c.submitted)}</td>
                    <td className="text-right tabular-nums">{pct(c.reply_rate as number | null)}</td>
                    <td className="text-right tabular-nums">{pct(c.hire_rate as number | null)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Cost and latency against budget">
          <table className="w-full text-sm">
            <tbody>
              <Row label="Jobs analysed" value={cl.jobs_analysed} />
              <Row label="p50 latency per job" value={cl.latency_p50_s_per_job} unit="s" />
              <Row label="p95 latency per job" value={cl.latency_p95_s_per_job} unit="s" budget={budget.latency_p95_seconds_per_job} />
              <Row label="p95 latency per proposal" value={cl.latency_p95_s_per_proposal} unit="s" budget={budget.latency_p95_seconds_per_proposal} />
              <Row label="Mean cost per job" value={cl.cost_usd_mean_per_job} unit="$" budget={budget.cost_usd_per_job_analysed} />
              <Row label="Mean cost per proposal" value={cl.cost_usd_mean_per_proposal} unit="$" budget={budget.cost_usd_per_proposal} />
              <Row label="Mean tokens per job" value={cl.tokens_mean_per_job} />
            </tbody>
          </table>
        </Card>
        <Card title="Top skip and rejection reasons">
          {a.rejection_reasons.length === 0 ? (
            <p className="text-sm text-muted">Nothing skipped or rejected yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {a.rejection_reasons.map((r) => (
                <li key={String(r.reason)} className="flex justify-between gap-2">
                  <span>{String(r.reason)}</span>
                  <span className="tabular-nums text-muted">{String(r.count)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Retrieval evaluation (dev set)">
          {Object.keys(retrieval).length === 0 ? (
            <p className="text-sm text-muted">Run make eval-rag to populate.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th className="text-left">Variant</th>
                  <th className="text-right">Recall@5</th>
                  <th className="text-right">MRR</th>
                  <th className="text-right">nDCG@10</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(retrieval).map(([v, r]) => (
                  <tr key={v} className="border-t border-border">
                    <td className="font-mono text-xs">{v}</td>
                    <td className="text-right tabular-nums">{r.overall?.["recall@5"]?.toFixed(3) ?? ""}</td>
                    <td className="text-right tabular-nums">{r.overall?.mrr?.toFixed(3) ?? ""}</td>
                    <td className="text-right tabular-nums">{r.overall?.["ndcg@10"]?.toFixed(3) ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value, unit, budget }: { label: string; value: unknown; unit?: string; budget?: number }) {
  const v = value === null || value === undefined ? null : Number(value);
  const over = budget !== undefined && v !== null && v > budget;
  const fmt = (x: number) => (unit === "$" ? `$${x.toFixed(4)}` : unit === "s" ? `${x} s` : String(x));
  return (
    <tr className="border-t border-border">
      <td className="py-1 text-muted">{label}</td>
      <td className={`py-1 text-right tabular-nums ${over ? "font-semibold text-rose-700 dark:text-rose-300" : ""}`}>{v === null ? "n/a" : fmt(v)}</td>
      <td className="py-1 pl-2 text-right text-xs text-muted">{budget !== undefined ? `budget ${fmt(budget)}` : ""}</td>
    </tr>
  );
}
