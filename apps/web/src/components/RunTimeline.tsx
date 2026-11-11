"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { StatusPill } from "./ui";

type RunEvent = { type: string; node?: string; status?: string | null; ts?: number; summary?: Record<string, unknown>; error?: string; history?: RunEvent[] };

const NODE_LABEL: Record<string, string> = {
  scout: "Scout fetched the job",
  analyst: "Job Analyst extracted the JobSpec",
  risk_assessor: "Risk Assessor scored the client",
  fit_matcher: "Fit Matcher mapped requirements to evidence",
  decision: "Decision",
  pricing: "Pricing Strategist quoted",
  writer: "Proposal Writer drafted",
  verifier: "Claims verified against evidence",
  critic: "Critic reviewed",
  compliance: "Compliance Guard checked policy",
  approval_prepare: "Prepared approval with dry-run preview",
  approval: "Human decision",
  submit: "Submitted to marketplace",
  fetch_messages: "Read new client messages",
  classify: "Classified intent",
  draft_reply: "Drafted a reply",
  send: "Reply sent",
};

function describe(e: RunEvent): string {
  const s = e.summary ?? {};
  const bits: string[] = [];
  if (s.decision) bits.push(`→ ${String(s.decision)}`);
  if (typeof s.fit === "number") bits.push(`fit ${Math.round(s.fit * 100)}`);
  if (typeof s.risk === "number") bits.push(`risk ${Math.round(s.risk * 100)}`);
  if (typeof s.price === "number") bits.push(`$${s.price}`);
  if (typeof s.words === "number") bits.push(`${s.words} words`);
  if (s.critique_passed !== undefined) bits.push(s.critique_passed ? "passed" : "sent back");
  if (s.compliance) bits.push(String(s.compliance));
  if (s.needs_attention) bits.push(String(s.needs_attention));
  return bits.join(" · ");
}

/** Live node-by-node progress over SSE. Reconnects on drop; a refresh replays buffered events. */
export function RunTimeline({ threadId, onFinished }: { threadId: string; onFinished?: (status: string) => void }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<string>("connecting");
  const qc = useQueryClient();
  const done = useRef(false);
  const finished = useRef(onFinished);
  useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    done.current = false;
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const finish = (st: string) => {
      done.current = true;
      setStatus(st);
      es?.close();
      qc.invalidateQueries();
      finished.current?.(st);
    };
    const connect = () => {
      es = new EventSource(`/api/runs/${threadId}/stream`, { withCredentials: true });
      es.addEventListener("snapshot", (m) => {
        const d = JSON.parse((m as MessageEvent).data) as RunEvent;
        setEvents((d.history ?? []).filter((e) => e.type === "node"));
        setStatus(d.status ?? "running");
      });
      es.addEventListener("node", (m) => {
        const d = JSON.parse((m as MessageEvent).data) as RunEvent;
        setEvents((prev) => [...prev, d]);
        if (d.status) setStatus(d.status);
      });
      es.addEventListener("interrupt", (m) => finish((JSON.parse((m as MessageEvent).data) as RunEvent).status ?? "awaiting_approval"));
      es.addEventListener("done", (m) => finish((JSON.parse((m as MessageEvent).data) as RunEvent).status ?? "done"));
      es.addEventListener("error", (m) => {
        const data = (m as MessageEvent).data;
        if (data) {
          finish("failed");
          return;
        }
        es?.close();
        if (!done.current) retry = setTimeout(connect, 2000);
      });
    };
    connect();
    return () => {
      done.current = true;
      es?.close();
      if (retry) clearTimeout(retry);
    };
  }, [threadId, qc]);

  return (
    <div data-testid="run-timeline">
      <div className="mb-2 flex items-center gap-2 text-sm">
        <span className="text-muted">Run status</span> <StatusPill status={status} />
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-muted">{status === "connecting" || status === "running" || status === "queued" ? "Waiting for the first agent to report…" : "No live events buffered for this run; see the trace below."}</p>
      ) : (
        <ol className="relative space-y-2 border-l border-border pl-4">
          {events.map((e, i) => (
            <li key={i} className="text-sm">
              <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-surface bg-accent" aria-hidden />
              <span className="font-medium">{NODE_LABEL[e.node ?? ""] ?? e.node}</span>{" "}
              <span className="text-muted">{describe(e)}</span>
              {e.ts && <span className="ml-2 text-xs tabular-nums text-muted">{new Date(e.ts * 1000).toLocaleTimeString()}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
