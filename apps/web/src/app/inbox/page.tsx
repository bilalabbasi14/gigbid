"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button, DecisionPill, EmptyState, ErrorState, inputCls, Meter, PageHeader, RiskBadge, Spinner, StatusPill } from "@/components/ui";
import { ago, api, call, money, type S } from "@/lib/client";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "bid", label: "Recommended bids" },
  { id: "watch", label: "Watch" },
  { id: "skip", label: "Skipped" },
  { id: "drafted", label: "Drafts to review" },
] as const;

export default function Inbox() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  const [q, setQ] = useState("");
  const [scoutQuery, setScoutQuery] = useState("");
  const query = {
    ...(filter === "drafted" ? { status: "drafted" } : filter !== "all" ? { decision: filter } : {}),
    ...(q ? { q } : {}),
  };
  const jobs = useQuery<S["JobListOut"]>({
    queryKey: ["jobs", query],
    queryFn: () => call(api.GET("/jobs", { params: { query } })),
    refetchInterval: (qr) => ((qr.state.data?.items ?? []).some((j) => j.status === "analysing" || j.status === "new") ? 5000 : 30000),
  });
  const scout = useMutation({
    mutationFn: () => call(api.POST("/jobs/scout", { body: { query: scoutQuery || null, limit: 20, analyse: true } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  const analyse = useMutation({
    mutationFn: (job_id: string) => call(api.POST("/jobs/{job_id}/analyse", { params: { path: { job_id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  const skip = useMutation({
    mutationFn: (job_id: string) => call(api.POST("/jobs/{job_id}/skip", { params: { path: { job_id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return (
    <div>
      <PageHeader
        title="Job inbox"
        subtitle="New jobs ranked by fit. Every job is analysed by three agents in parallel; you decide what gets a proposal."
        actions={
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              scout.mutate();
            }}
          >
            <label className="sr-only" htmlFor="scout-q">Search the marketplace</label>
            <input id="scout-q" className={inputCls + " w-48"} placeholder="Search marketplace…" value={scoutQuery} onChange={(e) => setScoutQuery(e.target.value)} />
            <Button type="submit" variant="primary" disabled={scout.isPending}>
              {scout.isPending ? "Scouting…" : "Find new jobs"}
            </Button>
          </form>
        }
      />
      {scout.data && (
        <p role="status" className="mb-3 text-sm text-muted">
          Found {scout.data.found} jobs, {scout.data.new} new{scout.data.queued.length ? `; analysing ${scout.data.queued.length}` : ""}.
        </p>
      )}
      {scout.error ? <div className="mb-3"><ErrorState error={scout.error} /></div> : null}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Filter" className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)} className={`rounded-full border px-3 py-1 text-sm ${filter === f.id ? "border-accent bg-surface font-medium" : "border-border text-muted"}`}>
              {f.label}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="filter-q">Filter by title</label>
        <input id="filter-q" className={inputCls + " ml-auto w-56"} placeholder="Filter by title…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {jobs.isLoading ? (
        <Spinner label="Loading jobs" />
      ) : jobs.error ? (
        <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
      ) : jobs.data!.items.length === 0 ? (
        <EmptyState title="No jobs here yet">Use “Find new jobs” to scout the marketplace, or add a saved search in Settings so GigBid scouts on a schedule.</EmptyState>
      ) : (
        <ul className="space-y-2" data-testid="job-list">
          {jobs.data!.items.map((j) => (
            <li key={j.job_id} className="rounded-lg border border-border bg-surface p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Link href={`/jobs/${j.job_id}`} className="font-medium hover:underline">
                    {j.title}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                    <DecisionPill decision={j.decision} />
                    <RiskBadge score={j.risk_score} flags={j.risk_flags} />
                    <StatusPill status={j.status} />
                    <span>{j.payment_type === "hourly" ? `hourly ${money(j.hourly_min)}–${money(j.hourly_max)}` : `fixed ${money(j.budget)}`}</span>
                    <span>{j.connects_cost} Connects</span>
                    {j.price_amount ? <span>our bid {money(j.price_amount, j.price_type)}</span> : null}
                    <span>{ago(j.first_seen_at)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Meter value={j.fit_score} label="Fit" />
                  {j.status === "drafted" && j.latest_thread_id ? (
                    <Link href={`/studio/${j.latest_thread_id}`} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white">
                      Review proposal
                    </Link>
                  ) : j.status === "new" || (!j.decision && j.status !== "analysing") ? (
                    <Button onClick={() => analyse.mutate(j.job_id)} disabled={analyse.isPending}>
                      Analyse
                    </Button>
                  ) : (
                    <Link href={`/jobs/${j.job_id}`} className="rounded-md border border-border px-3 py-1.5 text-sm">
                      Open
                    </Link>
                  )}
                  {j.status !== "dismissed" && j.status !== "submitted" && (
                    <Button variant="ghost" onClick={() => skip.mutate(j.job_id)} aria-label={`Skip ${j.title}`}>
                      Skip
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
