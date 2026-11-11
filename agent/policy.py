"""The marketplace policy pack (data/policy_pack/policy.yaml) as the agents see it.

A rule is data: an id, a severity (block | rewrite | warn), a description that the Writer and the
user see, the kinds of text it applies to, and detectors composed from the types below. A new rule
built from existing detector types is a YAML edit and a version bump, with no code change:

  - id: ai_disclosure
    severity: rewrite
    description: Proposals must say that they were drafted with AI assistance.
    applies_to: [proposal]
    detectors:
      - require_any: ["drafted with ai assistance"]

Detector types (string or one-key mapping):
  contact_details           email addresses, phone numbers, messaging handles
  links                     URLs
  {keywords: <list>}        any phrase of policy.keywords[<list>] as a substring
  {words: <list>}           any phrase of policy.keywords[<list>] as a whole word
  {regex: <pattern>}        a case-insensitive regular expression
  {max_words: <n>}          the text is longer than n words
  {require_any: [phrases]}  none of the phrases appears (case-insensitive)
  unsupported_claims        a claim the verifier labelled unsupported is still in the draft
Detectors on job text, not drafts (enforced elsewhere): injection_patterns. A rule without
detectors (human approval, fair use) is enforced by the architecture and listed for the record.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import yaml

from agent import settings
from agent.handoffs import ComplianceViolation
from agent.pii import EMAIL, HANDLE, PHONE, contains_contact_details

URL = re.compile(r"https?://\S+|www\.\S+", re.I)
KINDS = ("proposal", "message")
NOT_ON_DRAFTS = {"injection_patterns"}
# names used by policy pack v1 before detectors became composable
ALIASES: dict[str, Any] = {
    "email": "contact_details",
    "phone": "contact_details",
    "messaging_handle": "contact_details",
    "payment_link": "links",
    "off_platform_keyword": {"keywords": "off_platform"},
    "free_work_keyword": {"keywords": "free_work"},
    "guarantee_keyword": {"words": "guarantee"},
    "claim_verifier_unsupported": "unsupported_claims",
}

Hit = tuple[str, str]  # (detail, span)
Detector = Callable[[str, Any, dict[str, Any], list[dict[str, Any]]], Hit | None]


def _contact(
    text: str, _arg: Any, _pol: dict[str, Any], _claims: list[dict[str, Any]]
) -> Hit | None:
    found = contains_contact_details(text)
    if not found:
        return None
    spans = [m.group(0) for rx in (EMAIL, PHONE, HANDLE) for m in rx.finditer(text)][:3]
    return f"contact details: {', '.join(found)}", "; ".join(spans)


def _links(text: str, _arg: Any, _pol: dict[str, Any], _claims: list[dict[str, Any]]) -> Hit | None:
    m = URL.search(text)
    return ("link to an outside page", m.group(0)) if m else None


def _phrases(pol: dict[str, Any], name: str) -> list[str]:
    phrases = (pol.get("keywords") or {}).get(name)
    if phrases is None:
        raise ValueError(f"policy keywords list {name!r} is not defined")
    return [str(p).lower() for p in phrases]


def _keywords(
    text: str, name: Any, pol: dict[str, Any], _claims: list[dict[str, Any]]
) -> Hit | None:
    low = text.lower()
    for k in _phrases(pol, str(name)):
        if k in low:
            return f"'{k}' ({name})", k
    return None


def _words(text: str, name: Any, pol: dict[str, Any], _claims: list[dict[str, Any]]) -> Hit | None:
    low = text.lower()
    for k in _phrases(pol, str(name)):
        m = re.search(rf"\b{re.escape(k)}\b", low)
        if m:
            return f"'{k}' ({name})", text[max(0, m.start() - 40) : m.end() + 40]
    return None


def _regex(
    text: str, pattern: Any, _pol: dict[str, Any], _claims: list[dict[str, Any]]
) -> Hit | None:
    m = re.search(str(pattern), text, re.I)
    return (f"matches /{pattern}/", m.group(0)[:160]) if m else None


def _max_words(
    text: str, n: Any, _pol: dict[str, Any], _claims: list[dict[str, Any]]
) -> Hit | None:
    count = len(text.split())
    return (f"{count} words, limit {int(n)}", "") if count > int(n) else None


def _require_any(
    text: str, phrases: Any, _pol: dict[str, Any], _claims: list[dict[str, Any]]
) -> Hit | None:
    low = text.lower()
    wanted = [str(p) for p in (phrases if isinstance(phrases, list) else [phrases])]
    if any(p.lower() in low for p in wanted):
        return None
    return f"missing required wording, e.g. '{wanted[0]}'", ""


def _unsupported(
    _text: str, _arg: Any, _pol: dict[str, Any], claims: list[dict[str, Any]]
) -> Hit | None:
    for c in claims:
        if c.get("label") == "unsupported" and c.get("action") not in ("removed", "rewritten"):
            return "unsupported claim remains in the draft", str(c.get("text", ""))[:160]
    return None


DETECTORS: dict[str, Detector] = {
    "contact_details": _contact,
    "links": _links,
    "keywords": _keywords,
    "words": _words,
    "regex": _regex,
    "max_words": _max_words,
    "require_any": _require_any,
    "unsupported_claims": _unsupported,
}


def _normalise(det: Any) -> tuple[str, Any]:
    det = ALIASES.get(det, det) if isinstance(det, str) else det
    if isinstance(det, str):
        return det, None
    if isinstance(det, dict) and len(det) == 1:
        ((kind, arg),) = det.items()
        return str(kind), arg
    raise ValueError(f"detector must be a name or a one-key mapping, got {det!r}")


def validate(pol: dict[str, Any]) -> dict[str, Any]:
    """Resolve aliases and check every detector, so a broken pack fails at load, not mid-run."""
    for rule in pol.get("rules", []):
        if rule.get("severity") not in ("block", "rewrite", "warn"):
            raise ValueError(f"rule {rule.get('id')}: severity must be block, rewrite or warn")
        kinds = rule.setdefault("applies_to", list(KINDS))
        if not set(kinds) <= set(KINDS):
            raise ValueError(f"rule {rule['id']}: applies_to must be a subset of {KINDS}")
        resolved = []
        for det in rule.get("detectors") or []:
            kind, arg = _normalise(det)
            if kind not in DETECTORS and kind not in NOT_ON_DRAFTS:
                raise ValueError(f"rule {rule['id']}: unknown detector {kind!r}")
            if kind in ("keywords", "words"):
                _phrases(pol, str(arg))
            resolved.append((kind, arg))
        rule["_detectors"] = resolved
    return pol


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    path = settings.ROOT / settings.config().guardrails.get(
        "policy_file", "data/policy_pack/policy.yaml"
    )
    return validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def check(
    text: str, claims: list[dict[str, Any]] | None = None, kind: str = "proposal"
) -> list[ComplianceViolation]:
    """Every rule that applies to this kind of text, at most one violation per detector."""
    pol = load()
    out: list[ComplianceViolation] = []
    for rule in pol.get("rules", []):
        if kind not in rule["applies_to"]:
            continue
        for det, arg in rule["_detectors"]:
            if det in NOT_ON_DRAFTS:
                continue
            hit = DETECTORS[det](text, arg, pol, claims or [])
            if hit:
                out.append(
                    ComplianceViolation(
                        rule_id=rule["id"], severity=rule["severity"], detail=hit[0], span=hit[1]
                    )
                )
    return out


def describe(rule_id: str) -> str:
    return next(
        (r.get("description", "") for r in load().get("rules", []) if r["id"] == rule_id), ""
    )


def rules_for_writer(kind: str = "proposal") -> str:
    """The checkable rules, as the Writer and the Liaison see them (so they comply by design)."""
    lines = [
        f"- {r['description']}"
        for r in load().get("rules", [])
        if kind in r["applies_to"] and any(d not in NOT_ON_DRAFTS for d, _ in r["_detectors"])
    ]
    return "\n".join(lines) or "- (none)"


def version() -> int:
    return int(load().get("version", 0))


def pricing_minimums() -> dict[str, float]:
    p = load().get("pricing") or {}
    return {
        "hourly": float(p.get("min_hourly_usd") or 0),
        "fixed": float(p.get("min_fixed_usd") or 0),
    }
