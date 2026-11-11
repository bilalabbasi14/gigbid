"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { RunTimeline } from "@/components/RunTimeline";
import { Button, Card, ErrorState, PageHeader, Pill, Spinner, StatusPill } from "@/components/ui";
import { api, call, type S } from "@/lib/client";

const KIND_TONE = { tool_call: "blue", llm: "green", error: "red", interrupt: "amber", resume: "amber", observation: "gray", tool_result: "blue" } as const;

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const q = useQuery<S["RunDetailOut"]>({ queryKey: ["run", id], queryFn: () => call(api.GET("/runs/{thread_id}", { params: { path: { thread_id: id } } })) });
  const replay = useMutation({
    mutationFn: (checkpoint_id: string) => call(api.POST("/runs/{thread_id}/replay", { params: { path: { thread_id: id } }, body: { checkpoint_id } })),
    onSuccess: (r) => router.push(`/runs/${r.thread_id}`),
  });

  if (q.isLoading) return <Spinner label="Loading run" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const r = q.data!;
  const usage = r.usage as Record<string, number>;
  const live = ["queued", "running"].includes(r.status);
  const state = (r.state ?? {}) as Record<string, unknown>;
  const trace = r.trace ?? [];
  const checkpoints = r.checkpoints ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Run ${r.thread_id}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {r.kind} <StatusPill status={r.status} />
            {r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : null}
            {usage.input_tokens ? ` · ${usage.input_tokens} in / ${usage.output_tokens ?? 0} out tokens` : null}
            {r.cost_usd !== null && r.cost_usd !== undefined ? ` · $${r.cost_usd.toFixed(4)}` : null}
          </span>
        }
        actions={
          <>
            {r.trace_url && (
              <a href={r.trace_url} target="_blank" rel="noreferrer" className="rounded-md border border-border px-3 py-1.5 text-sm">
                Full trace in LangSmith
              </a>
            )}
            {r.status === "awaiting_approval" && r.kind === "bid" && (
              <Link href={`/studio/${r.thread_id}`} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white">
                Review proposal
              </Link>
            )}
            {r.job_id && (
              <Link href={`/jobs/${r.job_id}`} className="rounded-md border border-border px-3 py-1.5 text-sm">
                Job
              </Link>
            )}
          </>
        }
      />
      {r.needs_attention_reason && (
        <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-950 dark:text-rose-100">
          Needs attention: {r.needs_attention_reason}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Live progress">
            <RunTimeline threadId={id} onFinished={() => qc.invalidateQueries({ queryKey: ["run", id] })} />
          </Card>
          <Card title={`Execution trace (${trace.length} events)`}>
            {trace.length === 0 ? (
              <p className="text-sm text-muted">{live ? "The trace fills in as nodes finish." : "No trace recorded."}</p>
            ) : (
              <ol className="space-y-1.5 text-sm">
                {trace.map((ev, i) => {
                  const e = ev as Record<string, unknown>;
                  const kind = String(e.kind ?? "observation") as keyof typeof KIND_TONE;
                  return (
                    <li key={i} className="rounded border border-border p-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Pill tone={KIND_TONE[kind] ?? "gray"}>{kind}</Pill>
                        <span className="font-medium">{String(e.node ?? "")}</span>
                        <span className="font-mono text-xs text-muted">{String(e.name ?? "")}</span>
                        {e.duration_ms ? <span className="ml-auto text-xs tabular-nums text-muted">{String(e.duration_ms)} ms</span> : null}
                      </div>
                      {e.note ? <p className="mt-1 text-xs text-muted">{String(e.note)}</p> : null}
                      {e.args && Object.keys(e.args as object).length > 0 ? (
                        <details className="mt-1 text-xs">
                          <summary className="cursor-pointer text-muted">arguments and result</summary>
                          <pre className="mt-1 max-h-48 overflow-auto rounded bg-background p-2">{JSON.stringify({ args: e.args, result: e.result }, null, 2)}</pre>
                        </details>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            )}
          </Card>
        </div>
        <aside className="space-y-4">
          <Card title="Checkpoints">
            <p className="mb-2 text-xs text-muted">Every step is checkpointed in Postgres. Replay forks a new thread from any point.</p>
            <ol className="space-y-1 text-sm">
              {checkpoints.map((c) => {
                const cp = c as Record<string, unknown>;
                return (
                  <li key={String(cp.checkpoint_id)} className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      <span className="text-muted">step {String(cp.steps ?? "")}</span> {String(cp.node ?? cp.source ?? "")} {cp.status ? <span className="text-xs text-muted">({String(cp.status)})</span> : null}
                    </span>
                    {Array.isArray(cp.next) && (cp.next as string[]).length > 0 && (
                      <Button variant="ghost" className="text-xs" disabled={replay.isPending} onClick={() => replay.mutate(String(cp.checkpoint_id))}>
                        Replay
                      </Button>
                    )}
                  </li>
                );
              })}
            </ol>
          </Card>
          <Card title="Final state">
            <pre className="max-h-96 overflow-auto rounded bg-background p-2 text-xs">{JSON.stringify({ status: state.status, decision: state.decision, submission: state.submission, sent: state.sent, errors: state.errors }, null, 2)}</pre>
          </Card>
        </aside>
      </div>
    </div>
  );
}
