"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PortfolioSummary, PortfolioUploadForm } from "@/components/PortfolioUpload";
import { Button, Card, EmptyState, ErrorState, Field, inputCls, PageHeader, Pill, Spinner } from "@/components/ui";
import { api, call, type S } from "@/lib/client";
import { useMe } from "@/lib/hooks";

export default function SettingsPage() {
  const me = useMe();
  if (!me.data) return <Spinner />;
  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle="Autonomy, budgets, saved searches, connected accounts and everything GigBid has learned about you." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Preferences user={me.data} />
        <Searches />
        <Accounts />
        <Memory />
        <Card title="Portfolio" className="lg:col-span-2">
          <PortfolioSummary />
          {me.data.persona === "own" && (
            <div className="mt-4 border-t border-border pt-4">
              <PortfolioUploadForm />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Preferences({ user }: { user: S["UserOut"] }) {
  const qc = useQueryClient();
  const st = user.settings as Record<string, unknown>;
  const [form, setForm] = useState({
    persona: user.persona,
    hourly_rate: String(st.hourly_rate ?? ""),
    hourly_floor: String(st.hourly_floor ?? ""),
    min_project_budget: String(st.min_project_budget ?? ""),
    weekly_connects_budget: String(st.weekly_connects_budget ?? ""),
    autonomy: String(st.autonomy ?? "auto_skip"),
    marketplace_mode: String(st.marketplace_mode ?? "gigsim"),
  });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT("/settings", {
          body: {
            persona: form.persona as S["UserSettingsIn"]["persona"],
            hourly_rate: form.hourly_rate ? Number(form.hourly_rate) : null,
            hourly_floor: form.hourly_floor ? Number(form.hourly_floor) : null,
            min_project_budget: form.min_project_budget ? Number(form.min_project_budget) : null,
            weekly_connects_budget: form.weekly_connects_budget ? Number(form.weekly_connects_budget) : null,
            autonomy: form.autonomy as "manual" | "auto_skip",
            marketplace_mode: form.marketplace_mode as "gigsim" | "upwork_live",
          },
        }),
      ),
    onSuccess: (u) => {
      qc.setQueryData(["me"], u);
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <Card title="Autonomy, rates and budgets">
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Profile">
          <select className={inputCls} value={form.persona} onChange={set("persona")}>
            <option value="ai_ml">Demo: AI/ML engineer</option>
            <option value="fullstack">Demo: full-stack developer</option>
            <option value="data_analyst">Demo: data analyst</option>
            <option value="own">My own profile</option>
          </select>
        </Field>
        <Field label="Autonomy" hint="Auto-skip only. GigBid never sends without approval.">
          <select className={inputCls} value={form.autonomy} onChange={set("autonomy")}>
            <option value="auto_skip">Auto-skip clear non-fits and scams</option>
            <option value="manual">Show me every job</option>
          </select>
        </Field>
        <Field label="Hourly rate (USD)">
          <input className={inputCls} inputMode="decimal" value={form.hourly_rate} onChange={set("hourly_rate")} />
        </Field>
        <Field label="Hourly floor (USD)">
          <input className={inputCls} inputMode="decimal" value={form.hourly_floor} onChange={set("hourly_floor")} />
        </Field>
        <Field label="Minimum fixed project (USD)">
          <input className={inputCls} inputMode="decimal" value={form.min_project_budget} onChange={set("min_project_budget")} />
        </Field>
        <Field label="Weekly Connects budget">
          <input className={inputCls} inputMode="numeric" value={form.weekly_connects_budget} onChange={set("weekly_connects_budget")} />
        </Field>
        <Field label="Marketplace">
          <select className={inputCls} value={form.marketplace_mode} onChange={set("marketplace_mode")}>
            <option value="gigsim">GigSim simulator</option>
            <option value="upwork_live">Upwork (official MCP, drafts only)</option>
          </select>
        </Field>
        <div className="flex items-end gap-2 sm:col-span-2">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            Save
          </Button>
          {save.isSuccess && <span role="status" className="text-sm text-muted">Saved.</span>}
        </div>
        {save.error ? <div className="sm:col-span-2"><ErrorState error={save.error} /></div> : null}
      </form>
    </Card>
  );
}

function Searches() {
  const qc = useQueryClient();
  const q = useQuery<S["SavedSearchOut"][]>({ queryKey: ["searches"], queryFn: () => call(api.GET("/settings/searches")) });
  const [name, setName] = useState("");
  const [skills, setSkills] = useState("");
  const [interval, setInterval] = useState("180");
  const create = useMutation({
    mutationFn: () => call(api.POST("/settings/searches", { body: { name, query: name, skills: skills.split(",").map((s) => s.trim()).filter(Boolean), interval_minutes: Number(interval), enabled: true } })),
    onSuccess: () => {
      setName("");
      setSkills("");
      qc.invalidateQueries({ queryKey: ["searches"] });
    },
  });
  const remove = useMutation({
    mutationFn: (search_id: string) => call(api.DELETE("/settings/searches/{search_id}", { params: { path: { search_id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["searches"] }),
  });
  return (
    <Card title="Saved searches">
      {q.isLoading ? (
        <Spinner />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <ul className="mb-3 space-y-1 text-sm">
          {q.data!.length === 0 && <li className="text-muted">No saved searches. Add one and the worker scouts it on schedule.</li>}
          {q.data!.map((s) => (
            <li key={s.search_id} className="flex items-center justify-between gap-2">
              <span>
                <span className="font-medium">{s.name}</span> <span className="text-muted">every {s.interval_minutes} min{s.skills?.length ? ` · ${s.skills.join(", ")}` : ""}</span>
              </span>
              <Button variant="ghost" className="text-xs" onClick={() => remove.mutate(s.search_id)} aria-label={`Delete saved search ${s.name}`}>
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="grid gap-2 sm:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <input aria-label="Search query" className={inputCls} placeholder="Query, e.g. power bi" value={name} onChange={(e) => setName(e.target.value)} />
        <input aria-label="Required skills" className={inputCls} placeholder="Skills (optional)" value={skills} onChange={(e) => setSkills(e.target.value)} />
        <div className="flex gap-2">
          <select aria-label="Interval" className={inputCls} value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="60">hourly</option>
            <option value="180">every 3 h</option>
            <option value="720">twice a day</option>
          </select>
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            Add
          </Button>
        </div>
      </form>
    </Card>
  );
}

function Accounts() {
  const qc = useQueryClient();
  const q = useQuery<S["ConnectedAccount"][]>({ queryKey: ["accounts"], queryFn: () => call(api.GET("/settings/accounts")) });
  const [pat, setPat] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const github = useMutation({
    mutationFn: () => call(api.POST("/settings/accounts/github", { body: { token: pat } })),
    onSuccess: () => {
      setPat("");
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
  async function upwork() {
    setMsg(null);
    try {
      const r = (await call(api.POST("/settings/accounts/upwork/start"))) as { authorize_url: string };
      window.location.href = r.authorize_url;
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not connect Upwork");
    }
  }
  const disconnect = useMutation({
    mutationFn: (provider: string) => call(api.DELETE("/settings/accounts/{provider}", { params: { path: { provider } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
  return (
    <Card title="Connected accounts">
      {q.isLoading ? (
        <Spinner />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : (
        <ul className="space-y-2 text-sm">
          {q.data!.map((a) => (
            <li key={a.provider} className="flex flex-wrap items-center justify-between gap-2">
              <span className="capitalize">
                {a.provider} <Pill tone={a.connected ? "green" : "gray"}>{a.connected ? "connected" : "not connected"}</Pill>
              </span>
              {a.provider === "upwork" && !a.connected && <Button onClick={upwork}>Connect via OAuth</Button>}
              {a.provider !== "gigsim" && a.connected && (
                <Button variant="ghost" onClick={() => disconnect.mutate(a.provider)}>
                  Disconnect
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {msg && <p role="alert" className="mt-2 text-sm text-amber-800 dark:text-amber-200">{msg}</p>}
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          github.mutate();
        }}
      >
        <input aria-label="GitHub personal access token" type="password" className={inputCls} placeholder="GitHub token for repo ingestion" value={pat} onChange={(e) => setPat(e.target.value)} />
        <Button type="submit" disabled={!pat || github.isPending}>
          Save
        </Button>
      </form>
      {github.error ? <div className="mt-2"><ErrorState error={github.error} /></div> : null}
      <p className="mt-2 text-xs text-muted">Tokens are encrypted at rest and never logged.</p>
    </Card>
  );
}

function Memory() {
  const qc = useQueryClient();
  const q = useQuery<S["MemoryView"]>({ queryKey: ["memory"], queryFn: () => call(api.GET("/settings/memory")) });
  const del = useMutation({
    mutationFn: ({ kind, key, category }: { kind: string; key: string; category?: string }) => call(api.DELETE("/settings/memory/{kind}/{key}", { params: { path: { kind, key }, query: category ? { category } : {} } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory"] }),
  });
  const clear = useMutation({ mutationFn: () => call(api.DELETE("/settings/memory")), onSuccess: () => qc.invalidateQueries({ queryKey: ["memory"] }) });
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (!confirm) return;
    const t = setTimeout(() => setConfirm(false), 4000);
    return () => clearTimeout(t);
  }, [confirm]);
  return (
    <Card
      title="What GigBid has learned"
      actions={
        <Button variant={confirm ? "danger" : "ghost"} className="text-xs" onClick={() => (confirm ? clear.mutate() : setConfirm(true))}>
          {confirm ? "Click again to forget everything" : "Forget all"}
        </Button>
      }
    >
      {q.isLoading ? (
        <Spinner />
      ) : q.error ? (
        <ErrorState error={q.error} />
      ) : q.data!.style.length + q.data!.outcome.length === 0 ? (
        <EmptyState title="Nothing learned yet">
          Style rules are promoted after the same edit appears in three of your drafts; outcome hints after enough replies in a category. {q.data!.candidates.length} observations are being counted.
        </EmptyState>
      ) : (
        <div className="space-y-3 text-sm" data-testid="memory">
          {q.data!.style.length > 0 && (
            <div>
              <h3 className="mb-1 font-medium">Style rules (from your edits)</h3>
              <ul className="space-y-1">
                {q.data!.style.map((m) => (
                  <li key={String(m.key)} className="flex items-center justify-between gap-2">
                    <span>
                      {String(m.rule)} <span className="text-xs text-muted">seen {String(m.support)}×</span>
                    </span>
                    <Button variant="ghost" className="text-xs" onClick={() => del.mutate({ kind: "style", key: String(m.key) })}>
                      Delete
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {q.data!.outcome.length > 0 && (
            <div>
              <h3 className="mb-1 font-medium">What worked (from outcomes)</h3>
              <ul className="space-y-1">
                {q.data!.outcome.map((m) => (
                  <li key={String(m.key)} className="flex items-center justify-between gap-2">
                    <span>{String(m.hint)}</span>
                    <Button variant="ghost" className="text-xs" onClick={() => del.mutate({ kind: "outcome", key: String(m.key), category: String(m.category) })}>
                      Delete
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
