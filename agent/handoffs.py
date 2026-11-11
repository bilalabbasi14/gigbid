"""Typed hand-offs between agents (C3). Anything a later node decides on is one of these models,
never free text."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Decision = Literal["bid", "watch", "skip"]
ClaimLabel = Literal["supported", "partly_supported", "unsupported"]


class JobSpec(BaseModel):
    """Job Analyst output."""

    job_id: str
    title: str
    summary: str = Field(description="Two sentences: what the client wants and why")
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    budget_type: Literal["fixed", "hourly", "unknown"] = "unknown"
    budget_min: float | None = None
    budget_max: float | None = None
    timeline: str | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(
        default_factory=list, description="Unstated needs a good freelancer would address"
    )
    client_industry: str | None = None
    job_category: str | None = None
    red_flags_in_text: list[str] = Field(default_factory=list)


class RiskReport(BaseModel):
    """Risk Assessor output."""

    score: float = Field(ge=0, le=1, description="0 safe .. 1 certain scam")
    flags: list[str] = Field(default_factory=list)
    scam_likely: bool = False
    injection_detected: bool = False
    injection_patterns: list[str] = Field(default_factory=list)
    client_quality: float = Field(
        ge=0, le=1, default=0.5, description="0 poor .. 1 excellent client history"
    )
    explanation: str = ""


class EvidenceRef(BaseModel):
    evidence_id: str
    title: str
    type: str
    project_id: str | None = None
    excerpt: str = ""
    source: str = ""
    year: int | None = None
    outcome: str | None = None
    score: float = 0.0


class RequirementMatch(BaseModel):
    requirement: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    strength: Literal["strong", "partial", "none"] = "none"
    note: str = ""


class FitReport(BaseModel):
    """Fit Matcher output: every requirement mapped to portfolio evidence."""

    score: float = Field(ge=0, le=1)
    matrix: list[RequirementMatch] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    fit_score: float = 0.0
    risk_score: float = 0.0
    auto: bool = Field(default=False, description="True when auto-skipped by the autonomy setting")


class PriceQuote(BaseModel):
    """Pricing Strategist output."""

    bid_type: Literal["fixed", "hourly"]
    amount: float = Field(gt=0)
    floor: float = Field(description="The user's floor; never undercut")
    market_p25: float | None = None
    market_p50: float | None = None
    market_p75: float | None = None
    client_budget_min: float | None = None
    client_budget_max: float | None = None
    connects_cost: int = 0
    connects_balance: int | None = None
    expected_value: float = Field(default=0.0, description="p(win) x amount, rough")
    worth_connects: bool = True
    rationale: str = ""
    policy_version: int = 1


class Claim(BaseModel):
    claim_id: str
    text: str
    cited_evidence_ids: list[str] = Field(default_factory=list)
    label: ClaimLabel = "unsupported"
    support_score: float = 0.0
    best_evidence_id: str | None = None
    action: Literal["keep", "rewritten", "removed"] = "keep"


class ProposalDraft(BaseModel):
    """Proposal Writer output (and what the human edits)."""

    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    revision: int = 0
    word_count: int = 0
    claims: list[Claim] = Field(default_factory=list)
    verification: dict = Field(default_factory=dict)  # unsupported rate before/after, counts


class Critique(BaseModel):
    """Critic output."""

    passed: bool
    grounding_score: float = Field(ge=0, le=1)
    personalisation_score: float = Field(ge=0, le=1)
    length_ok: bool = True
    issues: list[str] = Field(default_factory=list)
    revision_instructions: str = ""
    round: int = 0


class ComplianceViolation(BaseModel):
    rule_id: str
    severity: Literal["block", "rewrite", "warn"]
    detail: str
    span: str | None = None


class ComplianceVerdict(BaseModel):
    """Compliance Guard output."""

    allowed: bool
    violations: list[ComplianceViolation] = Field(default_factory=list)
    rewritten_cover_letter: str | None = None
    policy_version: int = 1
    reason: str = ""


class ApprovalPayload(BaseModel):
    """What the human sees at the interrupt."""

    kind: Literal["proposal", "message", "connects_spend"]
    job_id: str
    thread_id: str
    draft: ProposalDraft
    evidence: list[EvidenceRef] = Field(default_factory=list)
    risk: RiskReport
    price: PriceQuote
    fit: FitReport | None = None
    job_spec: JobSpec | None = None
    critique: Critique | None = None
    compliance: ComplianceVerdict | None = None
    dry_run_preview: dict = Field(default_factory=dict)
    connects_cost: int = 0


class ApprovalDecision(BaseModel):
    """What the human sends back to resume the graph."""

    action: Literal["approve", "edit", "reject"]
    edited_cover_letter: str | None = None
    edited_answers: list[str] | None = None
    reason: str | None = None
    user_id: str | None = None


class SubmissionResult(BaseModel):
    proposal_id: str | None = None
    status: str
    connects_spent: int = 0
    thread_id: str | None = None
    idempotent_replay: bool = False


# ---- conversation graph ----
IntentLabel = Literal[
    "question",
    "negotiation",
    "interview_request",
    "scam_signal",
    "acceptance",
    "rejection",
    "other",
]


class IntentClassification(BaseModel):
    intent: IntentLabel
    confidence: float = Field(ge=0, le=1)
    injection_detected: bool = False
    summary: str = ""


class ReplyDraft(BaseModel):
    thread_id: str
    body: str
    proposed_slots: list[dict] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    intent: IntentLabel = "other"
