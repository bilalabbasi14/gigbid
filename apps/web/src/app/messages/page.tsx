"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApprovalPanel, type ApprovalAction } from "@/components/ApprovalPanel";
import { RunTimeline } from "@/components/RunTimeline";
import { Button, Card, EmptyState, ErrorState, inputCls, PageHeader, Pill, Spinner } from "@/components/ui";
import { ago, api, call, type S } from "@/lib/client";

export default function MessagesPage() {
  return (
    <Suspense fallback={<Spinner label="Loading conversations" />}>
      <Messages />
    </Suspense>
  );
}

function Messages() {
  const qc = useQueryClient();
  const params = useSearchParams();
  const threads = useQuery<S["ThreadOut"][]>({ queryKey: ["threads"], queryFn: () => call(api.GET("/messages/threads")), refetchInterval: 30_000 });
  const [picked, setSelected] = useState<string | null>(null);
  const selected = picked ?? params.get("thread") ?? threads.data?.[0]?.marketplace_thread_id ?? null;

  return (
    <div>
      <PageHeader title="Messages" subtitle="Client conversations. GigBid drafts replies and proposes interview slots; you approve before anything is sent." />
      {threads.isLoading ? (
        <Spinner label="Loading conversations" />
      ) : threads.error ? (
        <ErrorState error={threads.error} onRetry={() => threads.refetch()} />
      ) : threads.data!.length === 0 ? (
        <EmptyState title="No conversations yet">When a client replies to one of your proposals, the thread appears here.</EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          <nav aria-label="Conversations" className="space-y-1">
            {threads.data!.map((t) => (
              <button
                key={t.marketplace_thread_id}
                type="button"
                aria-current={selected === t.marketplace_thread_id ? "true" : undefined}
                onClick={() => setSelected(t.marketplace_thread_id)}
                className={`block w-full rounded-lg border p-2 text-left text-sm ${selected === t.marketplace_thread_id ? "border-accent bg-surface" : "border-border"}`}
              >
                <span className="line-clamp-1 font-medium">{t.job_title ?? t.marketplace_thread_id}</span>
                <span className="mt-0.5 flex flex-wrap gap-1 text-xs text-muted">
                  {t.unread > 0 && <Pill tone="blue">{t.unread} new</Pill>}
                  {t.pending_approval && <Pill tone="amber">reply waiting for you</Pill>}
                  {t.status && <span>{t.status}</span>}
                </span>
              </button>
            ))}
          </nav>
          <div className="md:col-span-2">{selected && <Thread key={selected} id={selected} onChanged={() => qc.invalidateQueries({ queryKey: ["threads"] })} />}</div>
        </div>
      )}
    </div>
  );
}

function Thread({ id, onChanged }: { id: string; onChanged: () => void }) {
  const qc = useQueryClient();
  const q = useQuery<S["MessagesOut"]>({ queryKey: ["thread", id], queryFn: () => call(api.GET("/messages/{marketplace_thread_id}", { params: { path: { marketplace_thread_id: id } } })) });
  const [runId, setRunId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [slot, setSlot] = useState<number>(0);
  const suggested = q.data?.suggested_reply ?? null;

  const draft = useMutation({
    mutationFn: () => call(api.POST("/messages/{marketplace_thread_id}/draft", { params: { path: { marketplace_thread_id: id } } })),
    onSuccess: (r) => setRunId(r.thread_id),
  });
  const decide = useMutation({
    mutationFn: (a: ApprovalAction) => {
      const slots = suggested?.proposed_slots ?? [];
      const body: S["ApprovalDecisionIn"] =
        a.action === "approve" ? { action: "approve", confirmed_slot: slots[slot] ?? null } : a.action === "edit" ? { action: "edit", edited_cover_letter: a.edited, confirmed_slot: slots[slot] ?? null } : { action: "reject", reason: a.reason };
      return call(api.POST("/approvals/{thread_id}", { params: { path: { thread_id: q.data!.conversation_thread_id! } }, body }));
    },
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["thread", id] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      onChanged();
    },
  });

  if (q.isLoading) return <Spinner label="Loading thread" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const msgs = q.data!.items;

  return (
    <div className="space-y-4">
      <Card title="Conversation">
        <ul className="space-y-2" data-testid="messages">
          {msgs.map((m) => {
            const mine = (m as Record<string, unknown>).sender === "freelancer";
            return (
              <li key={String((m as Record<string, unknown>).message_id)} className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${mine ? "ml-auto bg-indigo-50 dark:bg-indigo-950" : "bg-background"}`}>
                <p className="mb-0.5 text-xs text-muted">
                  {mine ? "You" : "Client"} · {ago(String((m as Record<string, unknown>).created_at ?? ""))}
                </p>
                <p className="whitespace-pre-line">{String((m as Record<string, unknown>).body ?? "")}</p>
              </li>
            );
          })}
        </ul>
      </Card>

      {suggested?.reply ? (
        <Card title="Suggested reply" actions={suggested.intent && <Pill tone={suggested.intent.intent === "scam_signal" ? "red" : "blue"}>{suggested.intent.intent.replaceAll("_", " ")}</Pill>}>
          {suggested.intent?.intent === "scam_signal" && (
            <p role="alert" className="mb-2 rounded bg-rose-50 p-2 text-sm text-rose-900 dark:bg-rose-950 dark:text-rose-100">
              This client asked to move contact or payment off the platform. The draft keeps everything on the marketplace.
            </p>
          )}
          {suggested.intent?.injection_detected && <p className="mb-2 text-sm text-amber-800 dark:text-amber-200">The message contained instructions aimed at an AI assistant; they were ignored.</p>}
          {editing ? (
            <textarea aria-label="Edit reply" className={inputCls + " min-h-40"} value={text} onChange={(e) => setText(e.target.value)} />
          ) : (
            <p className="whitespace-pre-line text-sm" data-testid="suggested-reply">{suggested.reply.body}</p>
          )}
          {(suggested.proposed_slots ?? []).length > 0 && (
            <fieldset className="mt-3 text-sm">
              <legend className="mb-1 font-medium">Interview slot to hold if the client confirms</legend>
              {(suggested.proposed_slots ?? []).map((s, i) => (
                <label key={i} className="mr-3 inline-flex items-center gap-1">
                  <input type="radio" name="slot" checked={slot === i} onChange={() => setSlot(i)} /> {new Date(String(s.start) + "Z").toLocaleString()}
                </label>
              ))}
            </fieldset>
          )}
          {suggested.compliance && !suggested.compliance.allowed && <ErrorState error={new Error(`Blocked by compliance: ${suggested.compliance.reason}`)} />}
          <div className="mt-3">
            {decide.error ? <div className="mb-2"><ErrorState error={decide.error} /></div> : null}
            <ApprovalPanel kind="message" editing={editing} editedText={text} dirty={text !== suggested.reply.body} busy={decide.isPending} onStartEdit={() => { setText(suggested.reply!.body); setEditing(true); }} onCancelEdit={() => { setText(suggested.reply!.body); setEditing(false); }} onDecide={(a) => decide.mutate(a)} />
          </div>
        </Card>
      ) : runId ? (
        <Card title="Drafting a reply">
          <RunTimeline threadId={runId} onFinished={() => qc.invalidateQueries({ queryKey: ["thread", id] })} />
        </Card>
      ) : (
        <Button variant="primary" onClick={() => draft.mutate()} disabled={draft.isPending}>
          Draft a reply
        </Button>
      )}
      {decide.data && decide.data.status !== "awaiting_approval" && (
        <p role="status" className="text-sm text-muted">
          Reply {decide.data.status === "submitted" ? "sent" : decide.data.status}.
        </p>
      )}
    </div>
  );
}
