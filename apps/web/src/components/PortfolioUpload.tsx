"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, call, upload, type S } from "@/lib/client";
import { Button, ErrorState, Field, inputCls, Pill, Spinner } from "./ui";

export function PortfolioSummary() {
  const q = useQuery<S["PortfolioOut"]>({ queryKey: ["portfolio"], queryFn: () => call(api.GET("/portfolio")) });
  if (q.isLoading) return <Spinner label="Loading portfolio" />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const p = q.data!;
  return (
    <div className="space-y-3 text-sm" data-testid="portfolio-summary">
      <p>
        {p.editable ? "Your own portfolio" : `Demo persona “${p.persona}” (read-only)`} · {p.indexed_chunks} indexed evidence chunks
      </p>
      <div className="flex flex-wrap gap-2">
        <Pill tone="blue">{p.counts.case_studies ?? 0} case studies</Pill>
        <Pill tone="blue">{p.counts.repos ?? 0} repositories</Pill>
        <Pill tone="blue">{p.counts.proposals ?? 0} past proposals</Pill>
        <Pill tone="blue">{p.counts.reviews ?? 0} reviews</Pill>
        <Pill tone={p.counts.cv ? "green" : "amber"}>{p.counts.cv ? "CV uploaded" : "no CV yet"}</Pill>
      </div>
      {p.top_skills.length > 0 && <p className="text-muted">Strongest evidenced skills: {p.top_skills.slice(0, 12).join(", ")}</p>}
      {p.projects.length > 0 && (
        <ul className="grid gap-1 sm:grid-cols-2">
          {p.projects.slice(0, 8).map((pr) => (
            <li key={pr.id} className="truncate">
              <span className="font-mono text-xs text-muted">{pr.id}</span> {pr.name} {pr.year ? `(${pr.year})` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PortfolioUploadForm() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<"cv" | "case_study" | "proposals" | "reviews">("case_study");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [skills, setSkills] = useState("");
  const [year, setYear] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setOk(null);
    const fd = new FormData();
    fd.set("kind", kind);
    fd.set("file", file);
    fd.set("title", title);
    fd.set("skills", skills);
    if (year) fd.set("year", year);
    try {
      await upload("/portfolio/upload", fd);
      setOk(`${file.name} uploaded; indexing in the background.`);
      setFile(null);
      setTitle("");
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2" data-testid="upload-form">
      <Field label="What is it?">
        <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="case_study">Case study (PDF, Markdown or text)</option>
          <option value="cv">CV (PDF or Markdown)</option>
          <option value="proposals">Past proposals with outcomes (JSONL)</option>
          <option value="reviews">Client reviews (JSONL)</option>
        </select>
      </Field>
      <Field label="File" hint="Up to 5 MB.">
        <input className={inputCls} type="file" accept=".pdf,.md,.txt,.jsonl,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      {kind === "case_study" && (
        <>
          <Field label="Title">
            <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Churn model for a fintech" />
          </Field>
          <Field label="Skills shown" hint="Comma separated.">
            <input className={inputCls} value={skills} onChange={(e) => setSkills(e.target.value)} placeholder="Python, scikit-learn, FastAPI" />
          </Field>
          <Field label="Year">
            <input className={inputCls} inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} />
          </Field>
        </>
      )}
      <div className="sm:col-span-2 space-y-2">
        {error ? <ErrorState error={error} /> : null}
        {ok && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{ok}</p>}
        <Button type="submit" variant="primary" disabled={!file || busy}>
          {busy ? "Uploading…" : "Upload"}
        </Button>
      </div>
    </form>
  );
}
