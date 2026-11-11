"use client";

import { useHealth } from "@/lib/hooks";

/** Shown whenever the marketplace or an MCP server is unreachable (work is queued, not lost), or
 * when the marketplace enforces a newer policy than GigBid's policy pack. */
export function DegradedBanner() {
  const { data, isError } = useHealth();
  const down = isError || (data && (!data.marketplace_reachable || data.status !== "ok"));
  if (!down && data?.policy_drift) {
    return (
      <div role="alert" data-testid="policy-drift-banner" className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
        <strong>Marketplace policy changed.</strong> The marketplace enforces policy v
        {data.marketplace_policy_version}; GigBid checks drafts against v{data.policy_version}. Review
        drafts carefully until the policy pack is updated.
      </div>
    );
  }
  if (!down) return null;
  const servers = data ? Object.keys(data.degraded ?? {}) : [];
  return (
    <div role="alert" data-testid="degraded-banner" className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
      <strong>{isError ? "GigBid API unreachable." : "Marketplace unavailable."}</strong>{" "}
      {isError
        ? "Retrying automatically; nothing you approved has been lost."
        : `New work is queued and will resume when ${data?.marketplace_mode === "upwork_live" ? "Upwork" : "GigSim"} is back${servers.length ? ` (affected: ${servers.join(", ")})` : ""}. Nothing is sent while degraded.`}
    </div>
  );
}
