"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/client";
import { useMe, usePendingApprovals } from "@/lib/hooks";
import { DegradedBanner } from "./DegradedBanner";
import { cx, Spinner } from "./ui";

const NAV = [
  { href: "/inbox", label: "Inbox" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/messages", label: "Messages" },
  { href: "/runs", label: "Agent runs" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
];
const PUBLIC = ["/login"];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const router = useRouter();
  const qc = useQueryClient();
  const isPublic = PUBLIC.some((p) => path.startsWith(p));
  const me = useMe();
  const pending = usePendingApprovals(!isPublic && me.isSuccess);
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === path; // navigating closes the menu without an effect

  useEffect(() => {
    if (isPublic) return;
    if (me.error instanceof ApiError && me.error.status === 401) router.replace(`/login?next=${encodeURIComponent(path)}`);
    else if (me.data && !me.data.onboarded && path !== "/onboarding") router.replace("/onboarding");
  }, [isPublic, me.error, me.data, path, router]);

  if (isPublic) return <>{children}</>;
  if (me.isLoading || !me.data) {
    return (
      <div className="mx-auto max-w-md p-8">
        <Spinner label="Signing you in" />
      </div>
    );
  }
  const onboarding = path === "/onboarding";
  const pendingCount = pending.data?.items.length ?? 0;

  async function logout() {
    await api.POST("/auth/logout");
    qc.clear();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-border bg-surface">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5">
          <Link href="/inbox" className="text-base font-semibold tracking-tight">
            GigBid
          </Link>
          {!onboarding && (
            <>
              <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
                {NAV.map((n) => (
                  <NavLink key={n.href} href={n.href} active={path.startsWith(n.href)} badge={n.href === "/inbox" ? pendingCount : 0}>
                    {n.label}
                  </NavLink>
                ))}
              </nav>
              <div className="flex items-center gap-2">
                <span className="hidden text-xs text-muted sm:inline" title={me.data.email}>
                  {me.data.display_name} · {me.data.persona === "own" ? "own profile" : me.data.persona}
                </span>
                <button type="button" onClick={logout} className="rounded px-2 py-1 text-sm text-muted hover:text-foreground">
                  Sign out
                </button>
                <button type="button" className="rounded border border-border px-2 py-1 text-sm md:hidden" aria-expanded={menuOpen} aria-controls="mobile-nav" onClick={() => setMenuPath(menuOpen ? null : path)}>
                  Menu
                </button>
              </div>
            </>
          )}
        </div>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Main mobile" className="border-t border-border px-4 py-2 md:hidden">
            {NAV.map((n) => (
              <NavLink key={n.href} href={n.href} active={path.startsWith(n.href)} badge={n.href === "/inbox" ? pendingCount : 0} block>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <DegradedBanner />
      {pendingCount > 0 && !onboarding && !path.startsWith("/studio") && (
        <div className="border-b border-indigo-200 bg-indigo-50 px-4 py-1.5 text-center text-sm text-indigo-950 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
          {pendingCount} item{pendingCount > 1 ? "s" : ""} waiting for your approval.{" "}
          <Link className="font-medium underline" href={pending.data!.items[0].kind === "proposal" ? `/studio/${pending.data!.items[0].thread_id}` : "/messages"}>
            Review now
          </Link>
        </div>
      )}
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}

function NavLink({ href, active, children, badge = 0, block = false }: { href: string; active: boolean; children: ReactNode; badge?: number; block?: boolean }) {
  return (
    <Link href={href} aria-current={active ? "page" : undefined} className={cx("rounded-md px-2.5 py-1.5 text-sm", block && "block", active ? "bg-background font-medium" : "text-muted hover:text-foreground")}>
      {children}
      {badge > 0 && <span className="ml-1.5 rounded-full bg-accent px-1.5 text-xs text-white">{badge}</span>}
    </Link>
  );
}
