"""Explicit promotion rules (R7). Nothing reaches long-term memory except through these two
functions, and both require repeated, consistent evidence before they write a rule.

Style memory   <- the user's edits to drafts.  Each edit yields *candidate patterns* (e.g.
                  "cut the opening sentence", "never say 'passionate'", "shorten by ~25%").
                  A candidate is promoted to a rule when the same pattern is seen in at least
                  `memory.style_promotion_min_edits` distinct edits (default 3).
Outcome memory <- submitted proposals with a known outcome, per job category. When a category
                  has at least `memory.outcome_promotion_min_samples` outcomes, features whose
                  reply rate beats the category average by a margin become hints.

Raw tool output, job text and client messages are never passed in; callers pass the structured
ProposalDraft / edit diff / outcome records.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from langgraph.store.base import BaseStore

from agent import settings
from agent.memory.store import _now, get_store

GENERIC_WORDS = [
    "passionate",
    "guru",
    "ninja",
    "rockstar",
    "synergy",
    "leverage",
    "world-class",
    "cutting-edge",
    "seamless",
    "best-in-class",
    "excited",
    "thrilled",
]


# ------------------------------------------------------------------ style memory
def edit_patterns(before: str, after: str) -> list[tuple[str, str]]:
    """Derive (pattern_key, human rule) candidates from one edit. Pure, testable."""
    out: list[tuple[str, str]] = []
    b_sents = re.split(r"(?<=[.!?])\s+", before.strip())
    a_sents = re.split(r"(?<=[.!?])\s+", after.strip())
    if b_sents and a_sents and b_sents[0] not in after and a_sents[0] != b_sents[0]:
        out.append(
            (
                "cut_first_sentence",
                "Always cut the opening sentence; start with the client's problem.",
            )
        )
    bw, aw = len(before.split()), len(after.split())
    if bw and aw < bw * 0.8:
        out.append(
            (
                "shorten",
                f"Keep the cover letter shorter: the user cut it by about {round(100 * (1 - aw / bw))}%.",
            )
        )
    for w in GENERIC_WORDS:
        if re.search(rf"\b{w}\b", before, re.I) and not re.search(rf"\b{w}\b", after, re.I):
            out.append((f"never_say:{w}", f"Never say '{w}'."))
    if "**" in before and "**" not in after:
        out.append(("no_bold", "Do not use bold markdown in proposals."))
    b_bul = len(re.findall(r"^\s*[-*•]\s", before, re.M))
    a_bul = len(re.findall(r"^\s*[-*•]\s", after, re.M))
    if b_bul >= 3 and a_bul == 0:
        out.append(("no_bullets", "Write in prose, not bullet lists."))
    if a_bul >= 3 and b_bul == 0:
        out.append(("use_bullets", "Use a short bullet list for the plan."))
    if before.count("!") > after.count("!"):
        out.append(("no_exclamation", "Avoid exclamation marks."))
    if re.search(r"\bI'm\b|\bI've\b|\bdon't\b", after) and not re.search(
        r"\bI'm\b|\bI've\b|\bdon't\b", before
    ):
        out.append(("contractions", "Use contractions; the tone should be conversational."))
    return out


def record_edit(
    user_id: str,
    before: str,
    after: str,
    *,
    job_category: str | None = None,
    store: BaseStore | None = None,
) -> list[str]:
    """Count candidate patterns for this edit; promote those that reached the threshold.
    Returns the rules promoted by this call (possibly empty)."""
    if not before or before == after:
        return []
    s = store or get_store()
    min_edits = int(settings.config().memory.get("style_promotion_min_edits", 3))
    promoted: list[str] = []
    for key, rule in edit_patterns(before, after):
        ns = ("candidates", user_id, "style")
        item = s.get(ns, key)
        count = (item.value.get("count", 0) if item else 0) + 1
        s.put(
            ns,
            key,
            {
                "pattern": key,
                "rule": rule,
                "count": count,
                "last_seen": _now(),
                "category": job_category,
            },
        )
        if count >= min_edits and s.get(("style", user_id), key) is None:
            s.put(
                ("style", user_id),
                key,
                {
                    "rule": rule,
                    "support": count,
                    "promoted_at": _now(),
                    "source": "user_edits",
                    "active": True,
                },
            )
            promoted.append(rule)
    return promoted


# ------------------------------------------------------------------ outcome memory
def proposal_features(
    draft: dict[str, Any], job: dict[str, Any], price: dict[str, Any] | None = None
) -> dict[str, bool]:
    """Boolean features of a proposal a hint can be phrased about."""
    letter = draft.get("cover_letter", "") or ""
    words = len(letter.split())
    first = letter.strip()[:200].lower()
    title_terms = {t for t in re.findall(r"[a-z]{4,}", (job.get("title") or "").lower())}
    f = {
        "opens_with_client_problem": bool(first)
        and not first.startswith(("i ", "i'm", "my ", "hello", "hi ", "dear")),
        "under_200_words": words < 200,
        "over_250_words": words > 250,
        "cites_2plus_evidence": len(draft.get("evidence_ids") or []) >= 2,
        "mentions_title_terms": sum(1 for t in title_terms if t in letter.lower()) >= 2,
        "answers_all_questions": len(draft.get("screening_answers") or [])
        >= len(job.get("screening_questions") or []),
        "has_milestone_plan": bool(
            re.search(r"\b(milestone|week ?\d|day ?\d|phase)\b", letter, re.I)
        ),
        "asks_a_question": "?" in letter,
    }
    if price and job.get("budget") and price.get("amount"):
        f["bids_below_budget"] = float(price["amount"]) < float(job["budget"])
    return f


def record_outcome(
    user_id: str,
    *,
    category: str,
    features: dict[str, bool],
    outcome: str,
    store: BaseStore | None = None,
) -> list[str]:
    """Store one outcome record (features + outcome) and promote hints when the category has
    enough samples. `outcome` is one of submitted|viewed|replied|interview|hired|lost.
    Returns the hints promoted by this call."""
    s = store or get_store()
    ns = ("candidates", user_id, f"outcome:{category}")
    key = f"o{len(s.search(ns, limit=1000)) + 1:04d}"
    positive = outcome in ("replied", "interview", "hired")
    s.put(ns, key, {"features": features, "outcome": outcome, "positive": positive, "ts": _now()})
    return promote_outcomes(user_id, category, store=s)


def promote_outcomes(user_id: str, category: str, *, store: BaseStore | None = None) -> list[str]:
    s = store or get_store()
    min_n = int(settings.config().memory.get("outcome_promotion_min_samples", 5))
    records = [
        i.value for i in s.search(("candidates", user_id, f"outcome:{category}"), limit=1000)
    ]
    if len(records) < min_n:
        return []
    base = sum(1 for r in records if r["positive"]) / len(records)
    promoted: list[str] = []
    feats = Counter(f for r in records for f in r["features"])
    for feat in feats:
        with_f = [r for r in records if r["features"].get(feat)]
        without = [r for r in records if feat in r["features"] and not r["features"].get(feat)]
        if len(with_f) < 3 or len(without) < 2:
            continue
        rate_with = sum(1 for r in with_f if r["positive"]) / len(with_f)
        rate_without = sum(1 for r in without if r["positive"]) / len(without)
        if rate_with - rate_without >= 0.25 and rate_with > base:
            hint = f"In {category} jobs, proposals that {feat.replace('_', ' ')} got replies {rate_with:.0%} of the time vs {rate_without:.0%} without (n={len(records)})."
            key = f"feat:{feat}"
            existing = s.get(("outcome", user_id, category), key)
            s.put(
                ("outcome", user_id, category),
                key,
                {
                    "hint": hint,
                    "feature": feat,
                    "rate_with": round(rate_with, 3),
                    "rate_without": round(rate_without, 3),
                    "n": len(records),
                    "promoted_at": existing.value.get("promoted_at") if existing else _now(),
                    "updated_at": _now(),
                    "active": existing.value.get("active", True) if existing else True,
                },
            )
            if existing is None:
                promoted.append(hint)
    return promoted
