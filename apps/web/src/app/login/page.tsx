"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, ErrorState, Field, inputCls } from "@/components/ui";
import { api, call } from "@/lib/client";

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user =
        mode === "login"
          ? await call(api.POST("/auth/login", { body: { email, password } }))
          : await call(api.POST("/auth/register", { body: { email, password, display_name: name, persona: "ai_ml" } }));
      qc.setQueryData(["me"], user);
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(!user.onboarded ? "/onboarding" : next && next.startsWith("/") ? next : "/inbox");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <h1 className="text-2xl font-semibold">GigBid</h1>
      <p className="mt-1 text-sm text-muted">Find, assess and bid on freelance work with proposals grounded in your portfolio. You approve everything before it leaves.</p>
      <div className="mt-6 flex gap-1 rounded-lg border border-border bg-surface p-1" role="tablist">
        {(["login", "register"] as const).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)} className={`flex-1 rounded-md px-3 py-1.5 text-sm ${mode === m ? "bg-background font-medium" : "text-muted"}`}>
            {m === "login" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="mt-4 space-y-3 rounded-lg border border-border bg-surface p-4">
        {mode === "register" && (
          <Field label="Your name">
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </Field>
        )}
        <Field label="Email">
          <input className={inputCls} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </Field>
        <Field label="Password" hint={mode === "register" ? "At least 8 characters." : undefined}>
          <input className={inputCls} type="password" required minLength={mode === "register" ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </Field>
        {error ? <ErrorState error={error} /> : null}
        <Button type="submit" variant="primary" className="w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
    </main>
  );
}
