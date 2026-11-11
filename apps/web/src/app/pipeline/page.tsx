"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect } from "react";
import { Button, EmptyState, ErrorState, PageHeader, Spinner } from "@/components/ui";
import { ago, api, call, money, type S } from "@/lib/client";

const STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"] as const;

export default function Pipeline() {
  const qc = useQueryClient();
  const board = useQuery<S["PipelineOut"]>({ queryKey: ["pipeline"], queryFn: () => call(api.GET("/pipeline")) });
  const sync = useMutation({
    mutationFn: () => call(api.POST("/pipeline/sync")),
    onSuccess: (d) => qc.setQueryData(["pipeline"], d),
  });
  const move = useMutation({
    mutationFn: ({ card_id, stage }: { card_id: string; stage: string }) => call(api.POST("/pipeline/{card_id}/stage", { params: { path: { card_id } }, body: { stage } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });
  // cards update from marketplace events; sync on open and every 30 s
  const { mutate } = sync;
  useEffect(() => {
    mutate();
    const t = setInterval(() => mutate(), 30_000);
    return () => clearInterval(t);
  }, [mutate]);

  const total = board.data ? Object.values(board.data.columns).reduce((n, c) => n + c.length, 0) : 0;
  return (
    <div>
      <PageHeader
        title="Pipeline"
        subtitle="Every proposal you approved, moved automatically as the marketplace reports views, replies and hires."
        actions={
          <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? "Syncing…" : "Sync now"}
          </Button>
        }
      />
      {sync.error ? <div className="mb-3"><ErrorState error={sync.error} /></div> : null}
      {board.isLoading ? (
        <Spinner label="Loading pipeline" />
      ) : board.error ? (
        <ErrorState error={board.error} onRetry={() => board.refetch()} />
      ) : total === 0 ? (
        <EmptyState title="No proposals yet">Approve a proposal in the studio and it appears here.</EmptyState>
      ) : (
        <div className="grid gap-3 overflow-x-auto pb-2 sm:grid-cols-2 lg:grid-cols-7" data-testid="kanban">
          {STAGES.map((stage) => {
            const cards = board.data!.columns[stage] ?? [];
            return (
              <section key={stage} aria-label={stage} className="min-w-44 rounded-lg border border-border bg-background p-2">
                <h2 className="mb-2 flex justify-between px-1 text-xs font-semibold uppercase text-muted">
                  {stage} <span className="tabular-nums">{cards.length}</span>
                </h2>
                <ul className="space-y-2">
                  {cards.map((c) => (
                    <li key={c.card_id} className="rounded-md border border-border bg-surface p-2 text-sm">
                      <Link href={`/jobs/${c.job_id}`} className="line-clamp-2 font-medium hover:underline">
                        {c.title}
                      </Link>
                      <p className="mt-1 text-xs text-muted">
                        {money(c.bid_amount, c.bid_type)} · {c.connects_spent} Connects · {ago(c.updated_at)}
                      </p>
                      {c.marketplace_thread_id && (
                        <Link href={`/messages?thread=${c.marketplace_thread_id}`} className="mt-1 inline-block text-xs underline">
                          Conversation
                        </Link>
                      )}
                      <label className="mt-1 block text-xs">
                        <span className="sr-only">Move {c.title} to stage</span>
                        <select className="w-full rounded border border-border bg-surface px-1 py-0.5 text-xs" value={c.stage} onChange={(e) => move.mutate({ card_id: c.card_id, stage: e.target.value })}>
                          {STAGES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </label>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
