"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { EmptyState, ErrorState, PageHeader, Spinner, StatusPill } from "@/components/ui";
import { ago, api, call, type S } from "@/lib/client";

export default function Runs() {
  const q = useQuery<S["RunOut"][]>({ queryKey: ["runs"], queryFn: () => call(api.GET("/runs", { params: { query: { limit: 100 } } })), refetchInterval: 10_000 });
  return (
    <div>
      <PageHeader title="Agent runs" subtitle="Every graph thread: bid analyses, conversations and portfolio builds, with latency, tokens and cost." />
      {q.isLoading ? (
        <Spinner label="Loading runs" />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data!.length === 0 ? (
        <EmptyState title="No runs yet">Analyse a job from the inbox to start one.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="px-3 py-2">Run</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Last node</th>
                <th className="px-3 py-2 text-right">Latency</th>
                <th className="px-3 py-2 text-right">Tokens</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2">Started</th>
              </tr>
            </thead>
            <tbody>
              {q.data!.map((r) => (
                <tr key={r.thread_id} className="border-t border-border">
                  <td className="px-3 py-2 font-mono text-xs">
                    <Link className="underline" href={`/runs/${r.thread_id}`}>
                      {r.thread_id}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{r.kind}</td>
                  <td className="px-3 py-2">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="px-3 py-2 text-muted">{r.current_node ?? ""}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : ""}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{Object.values(r.usage ?? {}).reduce((a: number, b) => a + Number(b), 0) || ""}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.cost_usd !== null && r.cost_usd !== undefined ? `$${r.cost_usd.toFixed(4)}` : ""}</td>
                  <td className="px-3 py-2 text-muted">{ago(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
