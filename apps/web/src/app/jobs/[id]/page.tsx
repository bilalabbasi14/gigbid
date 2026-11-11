"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { RunTimeline } from "@/components/RunTimeline";
import { Button, Card, DecisionPill, ErrorState, Meter, PageHeader, Pill, RiskBadge, Spinner, StatusPill, type Tone } from "@/components/ui";
import { api, call, money, pct, type S } from "@/lib/client";

const STRENGTH_TONE: Record<string, Tone> = { strong: "green", partial: "amber", none: "red" };

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery<S["JobDetailOut"]>({
    queryKey: ["job", id],
    queryFn: () => call(api.GET("/jobs/{job_id}", { params: { path: { job_id: id } } })),
    refetchInterval: (qr) => (qr.state.data?.record.status === "analysing" ? 4000 : false),
  });
  const analyse = useMutation({
    mutationFn: () => call(api.POST("/jobs/{job_id}/analyse", { params: { path: { job_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", id] }),
  });

  if (q.isLoading) return <Spinner label="Loading job" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const job = d.job as Record<string, unknown>;
  const running = d.record.status === "analysing";
  const awaiting = d.status === "awaiting_approval";

  return (
    <div className="space-y-4">
      <PageHeader
        title={d.record.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <DecisionPill decision={d.decision?.decision ?? d.record.decision} />
            <RiskBadge score={d.risk_report?.score ?? d.record.risk_score} flags={d.risk_report?.flags} />
            {d.status && <StatusPill status={d.status} />}
            <span>{d.record.connects_cost} Connects</span>
          </span>
        }
        actions={
          <>
            {awaiting && d.thread_id && (
              <Link href={`/studio/${d.thread_id}`} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white">
                Open proposal studio
              </Link>
            )}
            {d.thread_id && (
              <Link href={`/runs/${d.thread_id}`} className="rounded-md border border-border px-3 py-1.5 text-sm">
                Agent run
              </Link>
            )}
            {!running && (
              <Button onClick={() => analyse.mutate()} disabled={analyse.isPending}>
                {d.thread_id ? "Re-analyse" : "Analyse"}
              </Button>
            )}
          </>
        }
      />
      {d.needs_attention_reason && (
        <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:bg-rose-950 dark:text-rose-100">
          Needs attention: {d.needs_attention_reason}
        </div>
      )}
      {(running || analyse.isPending) && d.thread_id && (
        <Card title="Agents working">
          <RunTimeline threadId={d.thread_id} onFinished={() => qc.invalidateQueries({ queryKey: ["job", id] })} />
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {d.decision && (
            <Card title="Bid or skip">
              <p className="mb-2 text-sm">
                <DecisionPill decision={d.decision.decision} /> fit {pct(d.decision.fit_score)} · risk {pct(d.decision.risk_score)}
                {d.decision.auto ? " · decided automatically by your autonomy setting" : ""}
              </p>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {(d.decision.reasons ?? []).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </Card>
          )}

          {d.fit_report && (
            <Card title="Requirement → evidence" actions={<Meter value={d.fit_report.score} label="Fit" />}>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="evidence-matrix">
                  <thead className="text-xs uppercase text-muted">
                    <tr>
                      <th className="py-1 pr-3">Requirement</th>
                      <th className="py-1 pr-3">Fit</th>
                      <th className="py-1">Portfolio evidence that proves it</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(d.fit_report.matrix ?? []).map((m, i) => (
                      <tr key={i} className="border-t border-border align-top">
                        <td className="py-2 pr-3 font-medium">{m.requirement}</td>
                        <td className="py-2 pr-3">
                          <Pill tone={STRENGTH_TONE[m.strength]}>{m.strength}</Pill>
                        </td>
                        <td className="py-2">
                          {(m.evidence ?? []).length === 0 ? (
                            <span className="text-muted">No evidence: the writer may not claim this.</span>
                          ) : (
                            <ul className="space-y-1">
                              {(m.evidence ?? []).map((e) => (
                                <li key={e.evidence_id}>
                                  <span className="font-medium">{e.title}</span> <span className="text-xs text-muted">({e.type.replace("_", " ")}{e.year ? `, ${e.year}` : ""}{e.outcome ? `, ${e.outcome}` : ""})</span>
                                  <p className="line-clamp-2 text-xs text-muted">{e.excerpt}</p>
                                </li>
                              ))}
                            </ul>
                          )}
                          {m.note && <p className="mt-1 text-xs italic text-muted">{m.note}</p>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(d.fit_report.missing_skills ?? []).length > 0 && <p className="mt-2 text-sm text-muted">Missing: {(d.fit_report.missing_skills ?? []).join(", ")}</p>}
            </Card>
          )}

          {d.job_spec && (
            <Card title="JobSpec">
              <p className="mb-3 text-sm">{d.job_spec.summary}</p>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <SpecList label="Deliverables" items={d.job_spec.deliverables} />
                <SpecList label="Required skills" items={d.job_spec.required_skills} />
                <SpecList label="Nice to have" items={d.job_spec.nice_to_have_skills} />
                <SpecList label="Hidden needs" items={d.job_spec.hidden_needs} />
                <SpecList label="Screening questions" items={d.job_spec.screening_questions} />
                <div>
                  <dt className="text-xs uppercase text-muted">Budget and timeline</dt>
                  <dd>
                    {d.job_spec.budget_type} {money(d.job_spec.budget_min)}–{money(d.job_spec.budget_max)} · {d.job_spec.timeline ?? "no timeline"}
                  </dd>
                </div>
              </dl>
            </Card>
          )}

          <Card title="Original post (written by the client, treated as untrusted)">
            <p className="whitespace-pre-line text-sm text-muted">{String(job.description ?? "")}</p>
          </Card>
        </div>

        <div className="space-y-4">
          {d.risk_report && (
            <Card title="Risk report">
              <p className="mb-2 flex items-center gap-2 text-sm">
                <RiskBadge score={d.risk_report.score} /> client quality {pct(d.risk_report.client_quality)}
              </p>
              {d.risk_report.injection_detected && (
                <p className="mb-2 rounded bg-rose-50 p-2 text-sm text-rose-900 dark:bg-rose-950 dark:text-rose-100" data-testid="injection-flag">
                  Instructions aimed at AI assistants were found in this post and ignored ({(d.risk_report.injection_patterns ?? []).join(", ")}).
                </p>
              )}
              <div className="mb-2 flex flex-wrap gap-1">
                {(d.risk_report.flags ?? []).map((f) => (
                  <Pill key={f} tone="amber">{f.replaceAll("_", " ")}</Pill>
                ))}
              </div>
              <p className="text-sm text-muted">{d.risk_report.explanation}</p>
            </Card>
          )}
          {d.price_quote && (
            <Card title="Price">
              <p className="text-2xl font-semibold">{money(d.price_quote.amount, d.price_quote.bid_type)}</p>
              <p className="mt-1 text-sm text-muted">{d.price_quote.rationale}</p>
              <dl className="mt-3 grid grid-cols-2 gap-1 text-xs">
                <dt className="text-muted">Market p25–p75</dt>
                <dd>{money(d.price_quote.market_p25)}–{money(d.price_quote.market_p75)}</dd>
                <dt className="text-muted">Your floor</dt>
                <dd>{money(d.price_quote.floor)}</dd>
                <dt className="text-muted">Connects</dt>
                <dd>
                  {d.price_quote.connects_cost} (balance {d.price_quote.connects_balance ?? "n/a"})
                </dd>
                <dt className="text-muted">Worth the Connects</dt>
                <dd>{d.price_quote.worth_connects ? "yes" : "no"}</dd>
              </dl>
            </Card>
          )}
          {!d.thread_id && !analyse.isPending && <p className="text-sm text-muted">This job has not been analysed yet.</p>}
        </div>
      </div>
    </div>
  );
}

function SpecList({ label, items }: { label: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <dt className="text-xs uppercase text-muted">{label}</dt>
      <dd>
        <ul className="list-disc pl-4">
          {items.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      </dd>
    </div>
  );
}
