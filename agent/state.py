from typing import Any, TypedDict

class GigBidState(TypedDict, total=False):
    job: dict[str, Any]
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    decision: str
    evidence: list[dict[str, Any]]
    price_quote: dict[str, Any]
    proposal_draft: dict[str, Any]
    claim_verification: list[dict[str, Any]]
    critique: dict[str, Any]
    compliance_verdict: dict[str, Any]
    approval_status: str
    errors: list[str]
