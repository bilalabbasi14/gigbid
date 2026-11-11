"""Policy pack: composable detectors, validation, and a change request absorbed by YAML alone."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from agent import policy, settings
from agent.nodes import pricing

BASE = """
version: 2
keywords:
  guarantee: ["guarantee"]
rules:
  - id: no_guarantees
    severity: rewrite
    description: Do not guarantee results.
    detectors: [{words: guarantee}]
"""

# A simulated platform update: a disclosure line, a length cap and a banned phrase, in YAML only.
CHANGE_REQUEST = """
  - id: ai_disclosure
    severity: rewrite
    description: Proposals must say that they were drafted with AI assistance.
    applies_to: [proposal]
    detectors:
      - require_any: ["drafted with ai assistance", "ai-assisted"]
  - id: proposal_length
    severity: rewrite
    description: Cover letters are at most 30 words.
    applies_to: [proposal]
    detectors: [{max_words: 30}]
  - id: no_rating_requests
    severity: block
    description: Never ask the client for a five-star review.
    detectors: [{regex: "five[- ]star (review|rating)"}]
"""


def use(monkeypatch: pytest.MonkeyPatch, text: str) -> dict[str, Any]:
    pack = policy.validate(yaml.safe_load(text))
    monkeypatch.setattr(policy, "load", lambda: pack)
    return pack


def test_shipped_pack_is_valid_and_matches_config() -> None:
    policy.load.cache_clear()
    assert policy.version() == settings.config().policy_version
    ids = {r["id"] for r in policy.load()["rules"]}
    assert {"no_off_platform_contact", "no_guarantees", "no_fabrication"} <= ids


def test_shipped_pack_catches_contact_links_and_guarantees() -> None:
    policy.load.cache_clear()
    found = policy.check("Mail me at a@b.co, see https://x.io, I guarantee it.")
    assert [v.rule_id for v in found] == [
        "no_off_platform_contact",
        "no_off_platform_contact",
        "no_guarantees",
    ]


def test_unknown_detector_fails_at_load() -> None:
    with pytest.raises(ValueError, match="unknown detector"):
        policy.validate(yaml.safe_load(BASE.replace("{words: guarantee}", "{sentiment: 3}")))


def test_missing_keyword_list_fails_at_load() -> None:
    with pytest.raises(ValueError, match="not defined"):
        policy.validate(yaml.safe_load(BASE.replace("{words: guarantee}", "{words: nope}")))


def test_v1_detector_names_still_work() -> None:
    pack = policy.validate(
        yaml.safe_load(BASE.replace("[{words: guarantee}]", "[guarantee_keyword, email]"))
    )
    assert pack["rules"][0]["_detectors"] == [("words", "guarantee"), ("contact_details", None)]


def test_change_request_needs_no_code(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, BASE + CHANGE_REQUEST)
    long = " ".join(["word"] * 40) + " Please leave a five-star review."
    found = {v.rule_id: v.severity for v in policy.check(long, kind="proposal")}
    assert found == {
        "ai_disclosure": "rewrite",
        "proposal_length": "rewrite",
        "no_rating_requests": "block",
    }
    ok = "Short and AI-assisted, reviewed by me before sending."
    assert policy.check(ok, kind="proposal") == []


def test_rules_apply_only_to_their_kind_of_text(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, BASE + CHANGE_REQUEST)
    reply = "Happy to start Monday."  # a chat reply needs no disclosure line
    assert policy.check(reply, kind="message") == []
    assert [v.rule_id for v in policy.check(reply, kind="proposal")] == ["ai_disclosure"]


def test_new_rules_reach_the_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, BASE + CHANGE_REQUEST)
    rules = policy.rules_for_writer("proposal")
    assert "drafted with AI assistance" in rules and "at most 30 words" in rules
    assert "drafted with AI assistance" not in policy.rules_for_writer("message")


def test_pricing_respects_the_platform_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, BASE + "pricing: {min_hourly_usd: 40, min_fixed_usd: 300}\n")
    cfg = settings.config()
    prefs = {"hourly_rate": 10, "hourly_floor": 5, "min_project_budget": 20, "persona": "ai_ml"}
    hourly = pricing.quote(
        {"payment_type": "hourly", "hourly_min": 8, "hourly_max": 12},
        {},
        {},
        {},
        prefs,
        {},
        cfg,
        None,
        2,
    )
    fixed = pricing.quote(
        {"payment_type": "fixed", "budget": 100}, {}, {}, {}, prefs, {}, cfg, None, 2
    )
    assert hourly.amount == 40 and "platform minimum" in hourly.rationale
    assert fixed.amount == 300
