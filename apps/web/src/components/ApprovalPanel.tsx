"use client";

import { useState } from "react";
import { Button, Field, inputCls } from "./ui";

export type ApprovalAction = { action: "approve" } | { action: "edit"; edited: string } | { action: "reject"; reason: string };

/**
 * The human gate. Approve sends; Edit sends your text back through Compliance first (and teaches
 * style memory); Reject ends the run with a reason. Nothing leaves GigBid without one of these.
 */
export function ApprovalPanel({
  kind,
  editing,
  editedText,
  dirty,
  busy,
  costLabel,
  onStartEdit,
  onCancelEdit,
  onDecide,
}: {
  kind: "proposal" | "message";
  editing: boolean;
  editedText: string;
  dirty: boolean;
  busy: boolean;
  costLabel?: string;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onDecide: (a: ApprovalAction) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const noun = kind === "proposal" ? "proposal" : "reply";

  if (rejecting) {
    return (
      <div className="space-y-2" data-testid="reject-form">
        <Field label="Why are you rejecting this?" hint="Saved with the run and shown in Analytics under rejection reasons.">
          <textarea className={inputCls} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. budget too low, not my kind of client" autoFocus />
        </Field>
        <div className="flex gap-2">
          <Button variant="danger" disabled={busy || reason.trim().length < 3} onClick={() => onDecide({ action: "reject", reason: reason.trim() })}>
            Reject {noun}
          </Button>
          <Button onClick={() => setRejecting(false)} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="approval-panel">
      {editing ? (
        <>
          <Button variant="primary" disabled={busy || !dirty || editedText.trim().length < 20} onClick={() => onDecide({ action: "edit", edited: editedText })}>
            Save edit and re-check
          </Button>
          <Button onClick={onCancelEdit} disabled={busy}>
            Discard edit
          </Button>
        </>
      ) : (
        <>
          <Button variant="primary" disabled={busy} onClick={() => onDecide({ action: "approve" })}>
            {kind === "proposal" ? `Approve and submit${costLabel ? ` (${costLabel})` : ""}` : "Approve and send"}
          </Button>
          <Button onClick={onStartEdit} disabled={busy}>
            Edit
          </Button>
          <Button onClick={() => setRejecting(true)} disabled={busy}>
            Reject
          </Button>
        </>
      )}
      {busy && <span className="text-sm text-muted" role="status">Working…</span>}
    </div>
  );
}
