"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { EvidenceHover } from "@/components/EvidenceHover";
import { PortfolioSummary, PortfolioUploadForm } from "@/components/PortfolioUpload";
import { RunTimeline } from "@/components/RunTimeline";
import { Button, Card, EmptyState, ErrorState, Field, inputCls, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, call, pct, type S } from "@/lib/client";
import { useMe } from "@/lib/hooks";

export default function PortfolioPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Portfolio />
    </Suspense>
  );
}

function Portfolio() {
  const me = useMe();
  const params = useSearchParams();
  const [buildId, setBuildId] = useState<string | null>(params.get("build"));
  if (!me.data) return <Spinner />;
  return (
    <div className="space-y-4">
      <PageHeader title="Portfolio" subtitle="Everything GigBid can cite in a proposal. Every claim it writes must point at an item here." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="What GigBid can cite">
          <PortfolioSummary />
        </Card>
        <Builder onStarted={setBuildId} />
      </div>
      {buildId && <BuildReview key={buildId} threadId={buildId} />}
      {me.data.persona === "own" && (
        <Card title="Upload work">
          <PortfolioUploadForm />
        </Card>
      )}
    </div>
  );
}

function Builder({ onStarted }: { onStarted: (id: string) => void }) {
  const [source, setSource] = useState<"github" | "demo">("demo");
  const [owner, setOwner] = useState("");
  const [max, setMax] = useState("5");
  const start = useMutation({
    mutationFn: () => call(api.POST("/portfolio/github/build", { body: { source, owner: source === "github" ? owner : null, max_repos: Number(max) } })),
    onSuccess: (r) => onStarted(r.thread_id),
  });
  return (
    <Card title="Build case studies from GitHub">
      <p className="mb-3 text-sm text-muted">
        GigBid reads each repository through the official GitHub MCP server (read-only), extracts facts from the code (languages, dependencies, frameworks, tests, CI, containers, commit history), drafts a case study that cites a fact for every claim, and removes anything the code does not support. You approve each one before it joins your portfolio.
      </p>
      <form
        className="grid gap-3 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate();
        }}
      >
        <Field label="Source">
          <select className={inputCls} value={source} onChange={(e) => setSource(e.target.value as "github" | "demo")}>
            <option value="demo">Demo persona repositories</option>
            <option value="github">My GitHub account</option>
          </select>
        </Field>
        {source === "github" ? (
          <Field label="GitHub username" hint="Connect a read-only token in Settings first.">
            <input className={inputCls} value={owner} onChange={(e) => setOwner(e.target.value.trim())} placeholder="octocat" />
          </Field>
        ) : (
          <div />
        )}
        <Field label="Repositories">
          <select className={inputCls} value={max} onChange={(e) => setMax(e.target.value)}>
            {[3, 5, 8, 12].map((n) => (
              <option key={n} value={n}>
                up to {n}
              </option>
            ))}
          </select>
        </Field>
        <div className="sm:col-span-3">
          {start.error ? <div className="mb-2"><ErrorState error={start.error} /></div> : null}
          <Button type="submit" variant="primary" disabled={start.isPending || (source === "github" && !owner)}>
            {start.isPending ? "Starting…" : "Build case studies"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

type Decision = { action: "approve" | "edit" | "reject"; markdown?: string };

function BuildReview({ threadId }: { threadId: string }) {
  const qc = useQueryClient();
  const run = useQuery<S["RunOut"][]>({ queryKey: ["runs", "portfolio"], queryFn: () => call(api.GET("/runs", { params: { query: { kind: "portfolio", limit: 20 } } })), refetchInterval: 5000 });
  const status = run.data?.find((r) => r.thread_id === threadId)?.status ?? "queued";
  const approval = useQuery<S["ApprovalItem"]>({ queryKey: ["approval", threadId], queryFn: () => call(api.GET("/approvals/{thread_id}", { params: { path: { thread_id: threadId } } })), enabled: status === "awaiting_approval", retry: false });
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const submit = useMutation({
    mutationFn: () => call(api.POST("/approvals/{thread_id}", { params: { path: { thread_id: threadId } }, body: { action: "approve", portfolio_decisions: decisions } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio"] });
      qc.invalidateQueries({ queryKey: ["runs", "portfolio"] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (status === "queued" || status === "running" || status === "drafting") {
    return (
      <Card title="Building">
        <RunTimeline threadId={threadId} onFinished={() => qc.invalidateQueries({ queryKey: ["runs", "portfolio"] })} />
      </Card>
    );
  }
  if (submit.data || status === "submitted") {
    return (
      <Card title="Portfolio updated">
        <p className="text-sm" role="status">
          Approved case studies were added to your own portfolio and indexed. {submit.data?.status === "rejected" ? "Nothing was approved." : ""}
        </p>
      </Card>
    );
  }
  if (status !== "awaiting_approval") return <ErrorState error={new Error(`Build ${status.replaceAll("_", " ")}`)} />;
  if (approval.isLoading) return <Spinner label="Loading drafts" />;
  if (approval.error) return <ErrorState error={approval.error} />;
  const pf = approval.data?.portfolio;
  const drafts = pf?.drafts ?? [];
  if (!pf || drafts.length === 0) return <EmptyState title="No case studies could be drafted">The repositories had too little verifiable content.</EmptyState>;
  const set = (repo: string, d: Decision) => setDecisions((x) => ({ ...x, [repo]: d }));
  const decided = Object.keys(decisions).length;

  return (
    <div className="space-y-3" data-testid="build-review">
      <h2 className="text-lg font-semibold">Review {drafts.length} drafted case studies</h2>
      {drafts.map((d) => {
        const evidence: S["EvidenceRef"][] = (d.facts ?? []).map((f) => ({ evidence_id: f.fact_id, title: f.kind, type: "code_fact", excerpt: f.text, source: f.source, score: 1 }));
        const v = d.verification as Record<string, number>;
        const dec = decisions[d.repo];
        return (
          <Card
            key={d.repo}
            title={d.repo}
            actions={
              <span className="flex flex-wrap gap-1">
                <Pill tone="blue">{v.facts_total ?? 0} code facts</Pill>
                <Pill tone={v.unsupported_rate_after ? "amber" : "green"}>unsupported {pct(v.unsupported_rate_before)} → {pct(v.unsupported_rate_after)}</Pill>
                {v.removed ? <Pill tone="amber">{v.removed} removed</Pill> : null}
              </span>
            }
          >
            {editing === d.repo ? (
              <textarea aria-label={`Edit ${d.repo}`} className={inputCls + " min-h-64"} defaultValue={dec?.markdown ?? d.markdown} onBlur={(e) => set(d.repo, { action: "edit", markdown: e.target.value })} />
            ) : (
              <EvidenceHover text={(dec?.markdown ?? d.markdown).replace(/^#+\s*/gm, "")} evidence={evidence} claims={d.claims ?? []} />
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button variant={dec?.action === "approve" ? "primary" : "secondary"} onClick={() => set(d.repo, { action: "approve" })}>
                Approve
              </Button>
              <Button variant={dec?.action === "edit" ? "primary" : "secondary"} onClick={() => setEditing(editing === d.repo ? null : d.repo)}>
                {editing === d.repo ? "Done editing" : "Edit"}
              </Button>
              <Button variant={dec?.action === "reject" ? "danger" : "secondary"} onClick={() => set(d.repo, { action: "reject" })}>
                Reject
              </Button>
              {dec && <span className="text-sm text-muted">Marked: {dec.action}</span>}
            </div>
          </Card>
        );
      })}
      {submit.error ? <ErrorState error={submit.error} /> : null}
      <Button variant="primary" disabled={decided === 0 || submit.isPending} onClick={() => submit.mutate()}>
        Save {Object.values(decisions).filter((d) => d.action !== "reject").length} approved case studies
      </Button>
    </div>
  );
}
