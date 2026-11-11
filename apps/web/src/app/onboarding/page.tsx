"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PortfolioSummary, PortfolioUploadForm } from "@/components/PortfolioUpload";
import { Button, Card, ErrorState, Field, inputCls, PageHeader } from "@/components/ui";
import { api, call, type S } from "@/lib/client";
import { useMe } from "@/lib/hooks";

const PERSONAS = [
  { id: "ai_ml", name: "AI/ML engineer", blurb: "NLP, RAG systems, computer vision, MLOps" },
  { id: "fullstack", name: "Full-stack web developer", blurb: "React/Next.js, Node, Django, Postgres" },
  { id: "data_analyst", name: "Data analyst", blurb: "SQL, Power BI, Tableau, dbt, BigQuery" },
  { id: "own", name: "My own profile", blurb: "Upload your CV, case studies and past proposals" },
] as const;
const STEPS = ["Profile", "Marketplace", "Portfolio", "Rates and budget"] as const;

export default function Onboarding() {
  const me = useMe();
  const router = useRouter();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [persona, setPersona] = useState<string>(me.data?.persona ?? "ai_ml");
  const [mode, setMode] = useState<"gigsim" | "upwork_live">("gigsim");
  const [rate, setRate] = useState("55");
  const [floor, setFloor] = useState("30");
  const [minBudget, setMinBudget] = useState("100");
  const [connects, setConnects] = useState("80");
  const [autonomy, setAutonomy] = useState<"manual" | "auto_skip">("auto_skip");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [upworkMsg, setUpworkMsg] = useState<string | null>(null);

  async function save(body: S["UserSettingsIn"]) {
    const u = await call(api.PUT("/settings", { body }));
    qc.setQueryData(["me"], u);
    return u;
  }

  async function next() {
    setError(null);
    setBusy(true);
    try {
      if (step === 0) await save({ persona: persona as S["UserSettingsIn"]["persona"] });
      if (step === 1) await save({ marketplace_mode: mode });
      if (step === 2) qc.invalidateQueries({ queryKey: ["portfolio"] });
      if (step === 3) {
        await save({ hourly_rate: Number(rate), hourly_floor: Number(floor), min_project_budget: Number(minBudget), weekly_connects_budget: Number(connects), autonomy });
        if (search.trim()) await call(api.POST("/settings/searches", { body: { name: search.trim(), query: search.trim(), skills: [], interval_minutes: 180, enabled: true } }));
        await save({ onboarded: true });
        router.replace("/inbox");
        return;
      }
      setStep((s) => s + 1);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function connectUpwork() {
    setUpworkMsg(null);
    try {
      const r = await call(api.POST("/settings/accounts/upwork/start"));
      window.location.href = (r as { authorize_url: string }).authorize_url;
    } catch (err) {
      setUpworkMsg(err instanceof Error ? err.message : "Could not start the Upwork connection");
    }
  }

  return (
    <div className="mx-auto max-w-2xl" data-testid="onboarding">
      <PageHeader title="Set up GigBid" subtitle={`Step ${step + 1} of ${STEPS.length}: ${STEPS[step]}`} />
      <ol className="mb-5 flex gap-2" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined} className={`h-1.5 flex-1 rounded ${i <= step ? "bg-accent" : "bg-border"}`}>
            <span className="sr-only">{s}</span>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Card title="Whose portfolio should GigBid use?">
          <fieldset className="grid gap-2 sm:grid-cols-2">
            <legend className="sr-only">Profile</legend>
            {PERSONAS.map((p) => (
              <label key={p.id} className={`cursor-pointer rounded-lg border p-3 ${persona === p.id ? "border-accent bg-background" : "border-border"}`}>
                <input type="radio" name="persona" value={p.id} className="sr-only" checked={persona === p.id} onChange={() => setPersona(p.id)} />
                <span className="block font-medium">{p.name}</span>
                <span className="text-sm text-muted">{p.blurb}</span>
              </label>
            ))}
          </fieldset>
        </Card>
      )}

      {step === 1 && (
        <Card title="Connect a marketplace">
          <div className="space-y-3 text-sm">
            <label className="flex items-start gap-2">
              <input type="radio" name="mode" checked={mode === "gigsim"} onChange={() => setMode("gigsim")} className="mt-1" />
              <span>
                <span className="font-medium">GigSim</span> (connected). The marketplace simulator used for development and grading: real job posts, simulated clients, Connects and messages.
              </span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" name="mode" checked={mode === "upwork_live"} onChange={() => setMode("upwork_live")} className="mt-1" />
              <span>
                <span className="font-medium">Upwork</span> through the official Upwork MCP server (OAuth). Proposals and messages are created as drafts you confirm on Upwork. No scraping, no browser automation.
              </span>
            </label>
            {mode === "upwork_live" && (
              <div>
                <Button onClick={connectUpwork}>Connect Upwork account</Button>
                {upworkMsg && <p role="alert" className="mt-2 text-amber-800 dark:text-amber-200">{upworkMsg}</p>}
              </div>
            )}
          </div>
        </Card>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <Card title="Your portfolio">
            <PortfolioSummary />
          </Card>
          {persona === "own" ? (
            <Card title="Add work">
              <PortfolioUploadForm />
            </Card>
          ) : (
            <p className="text-sm text-muted">Demo personas come with a complete portfolio. Choose “My own profile” in step 1 to upload yours.</p>
          )}
        </div>
      )}

      {step === 3 && (
        <Card title="Rates, filters and budget">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Hourly rate (USD)">
              <input className={inputCls} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
            </Field>
            <Field label="Hourly floor (USD)" hint="GigBid never bids below this.">
              <input className={inputCls} inputMode="decimal" value={floor} onChange={(e) => setFloor(e.target.value)} />
            </Field>
            <Field label="Minimum fixed-price project (USD)">
              <input className={inputCls} inputMode="decimal" value={minBudget} onChange={(e) => setMinBudget(e.target.value)} />
            </Field>
            <Field label="Weekly Connects budget">
              <input className={inputCls} inputMode="numeric" value={connects} onChange={(e) => setConnects(e.target.value)} />
            </Field>
            <Field label="First saved search" hint="Optional. Scouted every 3 hours.">
              <input className={inputCls} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. machine learning" />
            </Field>
            <Field label="Autonomy" hint="GigBid never sends anything without your approval.">
              <select className={inputCls} value={autonomy} onChange={(e) => setAutonomy(e.target.value as typeof autonomy)}>
                <option value="auto_skip">Auto-skip clear non-fits and scams</option>
                <option value="manual">Show me every job</option>
              </select>
            </Field>
          </div>
        </Card>
      )}

      {error ? <div className="mt-4"><ErrorState error={error} /></div> : null}
      <div className="mt-5 flex justify-between">
        <Button onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>
          Back
        </Button>
        <Button variant="primary" onClick={next} disabled={busy}>
          {step === STEPS.length - 1 ? "Finish" : "Continue"}
        </Button>
      </div>
    </div>
  );
}
