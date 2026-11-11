"use client";

import { Fragment, useId, useState } from "react";
import type { S } from "@/lib/client";
import { cx, Pill, type Tone } from "./ui";

type Evidence = S["EvidenceRef"];
type Claim = S["Claim"];

const CITE = /\[([0-9a-f]{8,32})\]/g;
const LABEL_TONE: Record<Claim["label"], Tone> = { supported: "green", partly_supported: "amber", unsupported: "red" };

/**
 * Renders proposal text with every [evidence_id] citation as a focusable marker. Hover or focus
 * shows the portfolio evidence behind the claim and the verifier's label for it.
 */
export function EvidenceHover({ text, evidence, claims = [] }: { text: string; evidence: Evidence[]; claims?: Claim[] }) {
  const byId = new Map(evidence.map((e) => [e.evidence_id, e]));
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim());
  let n = 0;
  return (
    <div className="space-y-3 text-[15px] leading-relaxed" data-testid="evidence-text">
      {paragraphs.map((para, pi) => {
        const parts: (string | { id: string; idx: number })[] = [];
        let last = 0;
        for (const m of para.matchAll(CITE)) {
          parts.push(para.slice(last, m.index));
          parts.push({ id: m[1], idx: ++n });
          last = (m.index ?? 0) + m[0].length;
        }
        parts.push(para.slice(last));
        return (
          <p key={pi}>
            {parts.map((part, i) =>
              typeof part === "string" ? (
                <Fragment key={i}>{part}</Fragment>
              ) : (
                <Citation key={i} n={part.idx} ev={byId.get(part.id)} claim={claims.find((c) => c.cited_evidence_ids?.includes(part.id) || c.best_evidence_id === part.id)} id={part.id} />
              ),
            )}
          </p>
        );
      })}
    </div>
  );
}

function Citation({ n, ev, claim, id }: { n: number; ev?: Evidence; claim?: Claim; id: string }) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const tone: Tone = !ev ? "red" : claim ? LABEL_TONE[claim.label] : "blue";
  return (
    <span className="relative inline-block" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-describedby={open ? tipId : undefined}
        aria-label={`Evidence ${n}: ${ev ? ev.title : "unknown evidence"}`}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={cx("mx-0.5 rounded px-1 align-super text-[10px] font-semibold", tone === "red" ? "bg-rose-200 text-rose-900" : tone === "amber" ? "bg-amber-200 text-amber-900" : tone === "green" ? "bg-emerald-200 text-emerald-900" : "bg-indigo-200 text-indigo-900")}
        data-testid="citation"
      >
        {n}
      </button>
      {open && (
        <span role="tooltip" id={tipId} className="absolute bottom-full left-1/2 z-40 mb-2 block w-80 max-w-[85vw] -translate-x-1/2 rounded-lg border border-border bg-surface p-3 text-left text-xs shadow-lg">
          {ev ? (
            <>
              <span className="mb-1 flex flex-wrap items-center gap-1.5">
                <Pill tone="blue">{ev.type.replace("_", " ")}</Pill>
                {ev.year && <Pill>{ev.year}</Pill>}
                {ev.outcome && <Pill tone={ev.outcome === "won" ? "green" : "gray"}>{ev.outcome}</Pill>}
                {claim && <Pill tone={LABEL_TONE[claim.label]}>{claim.label.replace("_", " ")}</Pill>}
              </span>
              <span className="block font-semibold">{ev.title}</span>
              <span className="mt-1 block max-h-40 overflow-auto whitespace-pre-line text-muted">{ev.excerpt}</span>
              <span className="mt-1 block font-mono text-[10px] text-muted">{ev.source}</span>
            </>
          ) : (
            <span>Cites [{id}], which is not in the evidence set. Remove or replace this claim.</span>
          )}
        </span>
      )}
    </span>
  );
}
