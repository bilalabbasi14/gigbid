"""Simulated clients: hidden preferences and the decision engine.

Each client has preferences the freelancer never sees (must-have skills, a budget ceiling, a
dislike of generic openings, a preference for concise letters, whether screening answers matter).
Two decision modes, chosen by GIGSIM_CLIENT_MODE:
  rules  - deterministic scoring only (default; tests and quick runs)
  llm    - an open model also reads the proposal as that client (gigsim/client_llm.py); its
           interest is blended with the rule score (GIGSIM_LLM_WEIGHT, default 0.5) and the client
           writes its own reply. Decisions run in the background, like a real client's.
In both modes the dice are seeded on the job and the letter, so a proposal always gets the same
reaction, and the hidden preferences (must-have skills, budget ceiling) always count.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
import re
from typing import Any

GENERIC_OPENINGS = [
    "i am a passionate",
    "i'm a passionate",
    "dear sir",
    "dear madam",
    "dear hiring manager",
    "i hope this message finds you",
    "i have read your job",
    "i have gone through your",
    "i am writing to express",
    "i am very interested in your project",
    "hello sir",
    "respected",
    "i am confident that i am the best",
    "i am a highly motivated",
    "i can do this job",
]
SCREENING_TEMPLATES = [
    "Describe a project where you used {skill}. What was the outcome?",
    "What is your estimated timeline and how would you break the work into milestones?",
    "Have you worked with clients in a similar industry before? Give one example.",
    "How would you handle changing requirements midway through the project?",
    "Which part of this brief do you see as the main technical risk, and why?",
]
INDUSTRIES = [
    "e-commerce",
    "healthcare",
    "fintech",
    "education",
    "real estate",
    "logistics",
    "media",
    "SaaS",
    "non-profit",
    "hospitality",
]


def utc_offset_now(minutes: int) -> dt.datetime:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=minutes)).replace(tzinfo=None)


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


def make_hidden_prefs(
    client_id: str, skills: list[str], budget_hint: float | None, adversarial: bool
) -> dict[str, Any]:
    r = _rng("prefs", client_id)
    must = r.sample(skills, k=min(len(skills), r.choice([1, 2, 2, 3]))) if skills else []
    ceiling = (budget_hint or 500.0) * r.uniform(0.95, 1.3)
    return {
        "must_have_skills": must,
        "budget_ceiling": round(ceiling, 2),
        "dislikes_generic_opening": r.random() < 0.65,
        "prefers_concise": r.random() < 0.55,
        "max_words": r.choice([180, 250, 350]),
        "screening_matters": r.random() < 0.7,
        "values_specificity": r.random() < 0.8,
        "never_replies": adversarial,  # scam posters do not run a real hiring process
        "reply_warmth": round(r.uniform(0.3, 1.0), 2),
    }


def make_screening_questions(job_id: str, skills: list[str]) -> list[str]:
    r = _rng("screen", job_id)
    n = r.choice([0, 0, 1, 1, 2])
    qs = r.sample(SCREENING_TEMPLATES, k=n)
    return [q.format(skill=(skills[0] if skills else "the main technology")) for q in qs]


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def score_proposal(
    job: dict[str, Any], prefs: dict[str, Any], cover_letter: str, bid: float, answers: list[str]
) -> dict[str, Any]:
    """Deterministic client scoring. Returns breakdown + probabilities."""
    cl = cover_letter.lower()
    reasons: list[str] = []
    score = 0.0

    must = [s for s in prefs.get("must_have_skills", []) if s]
    if must:
        hit = sum(1 for s in must if s.lower() in cl)
        frac = hit / len(must)
        score += 0.35 * frac
        if frac < 1:
            reasons.append(f"missing must-have skills: {[s for s in must if s.lower() not in cl]}")
    else:
        score += 0.2

    first = cl.strip()[:160]
    if prefs.get("dislikes_generic_opening") and any(g in first for g in GENERIC_OPENINGS):
        score -= 0.25
        reasons.append("generic opening")

    title_terms = {w for w in re.findall(r"[a-z][a-z0-9+.#-]{3,}", job["title"].lower())}
    desc_terms = {w for w in re.findall(r"[a-z][a-z0-9+.#-]{5,}", job["description"].lower())}
    specific = len([w for w in (title_terms | desc_terms) if w in cl])
    if prefs.get("values_specificity"):
        score += min(0.2, 0.03 * specific)
        if specific < 3:
            reasons.append("not specific to the brief")

    ceiling = prefs.get("budget_ceiling") or 0
    if ceiling:
        if bid > ceiling:
            score -= 0.3
            reasons.append("bid above ceiling")
        elif bid < 0.35 * ceiling:
            score -= 0.1
            reasons.append("bid suspiciously low")
        else:
            score += 0.1

    if prefs.get("prefers_concise") and _words(cover_letter) > prefs.get("max_words", 250):
        score -= 0.1
        reasons.append("too long")

    if job.get("screening_questions"):
        answered = sum(1 for a in answers if a and len(a.strip()) > 20)
        if answered >= len(job["screening_questions"]):
            score += 0.1
        elif prefs.get("screening_matters"):
            score -= 0.15
            reasons.append("screening questions not answered")

    if re.search(r"\b(guarantee|guaranteed|100% success)\b", cl):
        score -= 0.1
        reasons.append("makes guarantees")

    return {"score": round(score, 3), "reasons": reasons, **probabilities(score, prefs)}


def probabilities(score: float, prefs: dict[str, Any]) -> dict[str, float]:
    warmth = prefs.get("reply_warmth", 0.6)
    p_reply = (
        0.0
        if prefs.get("never_replies")
        else max(0.02, min(0.95, 0.15 + score * 0.9)) * (0.6 + 0.4 * warmth)
    )
    return {
        "p_reply": round(p_reply, 3),
        "p_interview": round(max(0.1, min(0.9, 0.25 + score)), 3),
        "p_hire": round(max(0.1, min(0.8, 0.2 + score * 0.8)), 3),
    }


def mode() -> str:
    return os.environ.get("GIGSIM_CLIENT_MODE", "rules")


def decide(
    job: dict[str, Any],
    prefs: dict[str, Any],
    proposal_id: str,
    cover_letter: str,
    bid: float,
    answers: list[str],
    llm_view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return {'outcome': submitted|viewed|replied|interview|hired|lost, 'message': str|None,
    'breakdown': {...}}. `llm_view` is the client model's reading (client_llm.judge), if any."""
    breakdown = score_proposal(job, prefs, cover_letter, bid, answers)
    breakdown["mode"] = "rules"
    if llm_view is not None and not prefs.get("never_replies"):
        w = float(os.environ.get("GIGSIM_LLM_WEIGHT", "0.5"))
        blended = (1 - w) * breakdown["score"] + w * float(llm_view["interest"])
        breakdown.update(
            {
                "mode": "llm",
                "rule_score": breakdown["score"],
                "llm_interest": llm_view["interest"],
                "llm_concerns": llm_view.get("concerns", []),
                "llm_model": llm_view.get("model"),
                "score": round(blended, 3),
                **probabilities(blended, prefs),
            }
        )
    r = _rng("decide", proposal_id)
    outcome = "viewed" if r.random() < 0.85 else "submitted"
    message = None
    if outcome == "viewed" and r.random() < breakdown["p_reply"]:
        outcome = "replied"
        template = _client_reply(job, prefs, breakdown, bid, r)
        message = (llm_view or {}).get("reply") or template
        if r.random() < breakdown["p_interview"]:
            outcome = "interview"
            message += "\n\nCould you share a few times this week for a short call?"
            if r.random() < breakdown["p_hire"]:
                outcome = "hired"
    elif outcome == "viewed" and r.random() < 0.3:
        outcome = "lost"
    return {"outcome": outcome, "message": message, "breakdown": breakdown}


def _client_reply(
    job: dict[str, Any],
    prefs: dict[str, Any],
    breakdown: dict[str, Any],
    bid: float,
    r: random.Random,
) -> str:
    openers = [
        "Thanks for the proposal.",
        "Hi, thanks for applying.",
        "Appreciate the detailed note.",
    ]
    asks = [
        "Can you walk me through how you would approach the first milestone?",
        "What would your estimated timeline look like?",
        "Have you done something similar before? A link would help.",
        f"Is your rate of ${bid:g} negotiable for a longer engagement?",
        "One concern: we need this done in two weeks. Is that realistic?",
    ]
    if "bid above ceiling" in breakdown["reasons"]:
        asks.append(
            "Your price is above what we planned; is there a lighter scope you could offer?"
        )
    return f"{r.choice(openers)} {r.choice(asks)}"


def client_followup(prefs: dict[str, Any], freelancer_message: str, message_id: str) -> str | None:
    """Simple follow-up behaviour after a freelancer message in an open thread."""
    r = _rng("follow", message_id)
    if prefs.get("never_replies") or r.random() > 0.7:
        return None
    m = freelancer_message.lower()
    if any(w in m for w in ("slot", "call", "meeting", "available", "time")):
        return r.choice(
            [
                "Tuesday 3pm works for me. I will send an invite.",
                "Thursday morning is good. Does 10am your time work?",
            ]
        )
    if any(w in m for w in ("rate", "price", "budget", "cost")):
        return r.choice(
            [
                "That is a bit higher than planned. Could you do a fixed price for the first milestone?",
                "Understood on the rate. Let's start with a small paid milestone.",
            ]
        )
    return r.choice(
        [
            "Thanks, that answers my question. What do you need from me to start?",
            "Great. Can you send a short plan for the first week?",
        ]
    )


def industry_for(client_id: str) -> str:
    return _rng("industry", client_id).choice(INDUSTRIES)
