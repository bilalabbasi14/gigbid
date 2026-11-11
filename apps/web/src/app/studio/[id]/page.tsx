"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApprovalPanel, type ApprovalAction } from "@/components/ApprovalPanel";
import { EvidenceHover } from "@/components/EvidenceHover";
import { Button, Card, ErrorState, inputCls, Meter, PageHeader, Pill, RiskBadge, Spinner, type Tone } from "@/components/ui";
import { ApiError, api, call, money, pct, type S } from "@/lib/client";

const LABEL_TONE: Record<string, Tone> = { supported: "green", partly_supported: "amber", unsupported: "red" };

export default function Studio() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery<S["ApprovalItem"]>({ queryKey: ["approval", id], queryFn: () => call(api.GET("/approvals/{thread_id}", { params: { path: { thread_id: id } } })) });
  const p = q.data?.proposal ?? null;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [result, setResult] = useState<S["ApprovalResultOut"] | null>(null);

  const decide = useMutation({
    mutationFn: (a: ApprovalAction) =>
      call(
        api.POST("/approvals/{thread_id}", {
          params: { path: { thread_id: id } },
          body: a.action === "approve" ? { action: "approve" } : a.action === "edit" ? { action: "edit", edited_cover_letter: a.edited } : { action: "reject", reason: a.reason },
        }),
      ),
    onSuccess: (r) => {
      setResult(r);
      setEditing(false);
      if (r.next_proposal) qc.setQueryData(["approval", id], { ...q.data!, proposal: r.next_proposal });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const regen = useMutation({
    mutationFn: (paragraph_index: number) => call(api.POST("/proposals/{thread_id}/regenerate", { params: { path: { thread_id: id } }, body: { paragraph_index, instruction: "" } })),
    onSuccess: (r) => {
      setText(r.cover_letter);
      setEditing(true);
    },
  });

  if (q.isLoading) return <Spinner label="Loading proposal" />;
  if (q.error) {
    const notWaiting = q.error instanceof ApiError && q.error.status === 409;
    return (
      <div className="space-y-3">
        <ErrorState error={notWaiting ? new Error("This run is no longer waiting for approval.") : q.error} />
        <Link className="text-sm underline" href={`/runs/${id}`}>
          See the run
        </Link>
      </div>
    );
  }
  if (!p) return <ErrorState error={new Error("This approval is a message; open it from Messages.")} />;

  if (result && result.status !== "awaiting_approval") {
    return (
      <div className="mx-auto max-w-xl space-y-3" data-testid="approval-result">
        <PageHeader title={result.status === "submitted" ? "Proposal submitted" : result.status === "rejected" ? "Proposal rejected" : `Run ${result.status.replaceAll("_", " ")}`} />
        {result.submission && (
          <Card>
            <p className="text-sm">
              Proposal {String(result.submission.proposal_id)} is {String(result.submission.status)}. {String(result.submission.connects_spent)} Connects spent.
            </p>
          </Card>
        )}
        {result.status === "blocked" && <ErrorState error={new Error("Your edit was blocked by the Compliance Guard. Remove contact details, links or guarantees and try again from the job page.")} />}
        {(result.promoted_style_rules ?? []).length > 0 && (
          <Card title="GigBid learned from your edits">
            <ul className="list-disc pl-5 text-sm">
              {(result.promoted_style_rules ?? []).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </Card>
        )}
        <div className="flex gap-2">
          <Link href="/pipeline" className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white">
            Pipeline
          </Link>
          <Link href="/inbox" className="rounded-md border border-border px-3 py-1.5 text-sm">
            Back to inbox
          </Link>
        </div>
      </div>
    );
  }

  const draft = p.draft;
  const evidence = p.evidence ?? [];
  const claims = draft.claims ?? [];
  const ver = (draft.verification ?? {}) as Record<string, unknown>;
  const paragraphs = draft.cover_letter.split(/\n\s*\n/).filter((x) => x.trim());
  const words = text.trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="space-y-4">
      <PageHeader
        title={q.data!.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            Proposal studio · revision {draft.revision} · {draft.word_count} words
            <RiskBadge score={p.risk.score} flags={p.risk.flags} />
          </span>
        }
        actions={
          <Link href={`/jobs/${p.job_id}`} className="rounded-md border border-border px-3 py-1.5 text-sm">
            Job analysis
          </Link>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Cover letter" actions={!editing && <span className="text-xs text-muted">Hover or focus a number to see its evidence</span>}>
            {editing ? (
              <div>
                <label htmlFor="editor" className="sr-only">
                  Edit cover letter
                </label>
                <textarea id="editor" data-testid="draft-editor" className={inputCls + " min-h-80 font-[inherit] leading-relaxed"} value={text} onChange={(e) => setText(e.target.value)} />
                <p className="mt-1 text-xs text-muted">{words} words · edits are re-checked by Compliance and repeated patterns become style rules.</p>
              </div>
            ) : (
              <EvidenceHover text={draft.cover_letter} evidence={evidence} claims={claims} />
            )}
            {!editing && paragraphs.length > 1 && (
              <div className="mt-3 flex flex-wrap gap-1">
                {paragraphs.map((_, i) => (
                  <Button key={i} variant="ghost" className="text-xs" disabled={regen.isPending} onClick={() => regen.mutate(i)}>
                    Regenerate paragraph {i + 1}
                  </Button>
                ))}
              </div>
            )}
            {regen.error ? <div className="mt-2"><ErrorState error={regen.error} /></div> : null}
          </Card>

          {(draft.screening_answers ?? []).length > 0 && (
            <Card title="Screening answers">
              <ol className="space-y-3">
                {(draft.screening_answers ?? []).map((a, i) => (
                  <li key={i} className="text-sm">
                    <p className="mb-1 font-medium">{p.job_spec?.screening_questions?.[i] ?? `Question ${i + 1}`}</p>
                    <EvidenceHover text={a} evidence={evidence} claims={claims} />
                  </li>
                ))}
              </ol>
            </Card>
          )}

          <div className="sticky bottom-0 rounded-lg border border-border bg-surface p-3 shadow-sm">
            {decide.error ? <div className="mb-2"><ErrorState error={decide.error} /></div> : null}
            {result?.status === "awaiting_approval" && <p className="mb-2 text-sm text-emerald-700 dark:text-emerald-300" role="status">Your edit passed compliance. Review once more, then approve.</p>}
            <ApprovalPanel
              kind="proposal"
              editing={editing}
              editedText={text}
              dirty={text !== draft.cover_letter}
              busy={decide.isPending}
              costLabel={`${p.connects_cost} Connects`}
              onStartEdit={() => {
                setText(draft.cover_letter);
                setEditing(true);
              }}
              onCancelEdit={() => {
                setText(draft.cover_letter);
                setEditing(false);
              }}
              onDecide={(a) => decide.mutate(a)}
            />
          </div>
        </div>

        <aside className="space-y-4">
          <Card title="What will be sent (dry run)">
            <dl className="grid grid-cols-2 gap-1 text-sm" data-testid="dry-run">
              <dt className="text-muted">Bid</dt>
              <dd>{money(p.price.amount, p.price.bid_type)}</dd>
              <dt className="text-muted">Connects</dt>
              <dd>
                {String((p.dry_run_preview as Record<string, unknown>)?.connects_cost ?? p.connects_cost)}
                {(p.dry_run_preview as Record<string, unknown>)?.balance_after !== undefined && ` (balance after ${String((p.dry_run_preview as Record<string, unknown>).balance_after)})`}
              </dd>
              <dt className="text-muted">Answers</dt>
              <dd>{(draft.screening_answers ?? []).length}</dd>
            </dl>
            {(p.dry_run_preview as Record<string, unknown>)?.error ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-200">Preview unavailable: {String((p.dry_run_preview as Record<string, unknown>).error)}</p> : null}
            <p className="mt-2 text-xs text-muted">{p.price.rationale}</p>
          </Card>

          {p.critique && (
            <Card title="Critic" actions={<Pill tone={p.critique.passed ? "green" : "amber"}>{p.critique.passed ? "passed" : `round ${p.critique.round}`}</Pill>}>
              <div className="mb-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span>Grounding</span> <Meter value={p.critique.grounding_score} label="Grounding" />
                </div>
                <div className="flex justify-between">
                  <span>Personalisation</span> <Meter value={p.critique.personalisation_score} label="Personalisation" />
                </div>
              </div>
              <ul className="list-disc pl-5 text-sm text-muted">
                {(p.critique.issues ?? []).map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </Card>
          )}

          {p.compliance && (
            <Card title="Compliance Guard" actions={<Pill tone={p.compliance.allowed ? "green" : "red"}>{p.compliance.allowed ? "allowed" : "blocked"}</Pill>}>
              <p className="text-sm text-muted">{p.compliance.reason}</p>
              {(p.compliance.violations ?? []).map((v, i) => (
                <p key={i} className="mt-1 text-sm">
                  <Pill tone={v.severity === "block" ? "red" : "amber"}>{v.rule_id.replaceAll("_", " ")}</Pill> {v.detail}
                </p>
              ))}
              <p className="mt-2 text-xs text-muted">Policy version {p.compliance.policy_version}</p>
            </Card>
          )}

          <Card title="Claim verification">
            <p className="mb-2 text-sm text-muted">
              Unsupported claims: {pct(ver.unsupported_rate_before as number)} before repair → {pct(ver.unsupported_rate_after as number)} after. {String(ver.removed ?? 0)} removed, {String(ver.rewritten ?? 0)} rewritten.
            </p>
            <ul className="space-y-1.5" data-testid="claims">
              {claims.map((c) => (
                <li key={c.claim_id} className="text-sm">
                  <Pill tone={LABEL_TONE[c.label]}>{c.label.replace("_", " ")}</Pill> {c.action !== "keep" && <Pill>{c.action}</Pill>} <span className={c.action === "removed" ? "line-through text-muted" : ""}>{c.text}</span>
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
