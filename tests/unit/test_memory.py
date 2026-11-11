from langgraph.store.memory import InMemoryStore

from agent.memory import promotion_rules as pr
from agent.memory.store import clear_memory, delete_memory, list_memory, outcome_hints, style_rules

BEFORE = "I am a passionate developer excited to help! I built a RAG bot [abc]. **Plan:** week 1 ingest, week 2 UI."
AFTER = "You need answers from your manuals with citations. I built a RAG bot [abc]. Plan: week 1 ingest, week 2 UI."


def test_edit_patterns_are_derived_not_raw_text():
    pats = dict(pr.edit_patterns(BEFORE, AFTER))
    assert (
        "cut_first_sentence" in pats
        and "never_say:passionate" in pats
        and "no_bold" in pats
        and "no_exclamation" in pats
    )
    assert all(BEFORE not in rule for rule in pats.values())  # memory stores rules, never the draft


def test_style_rule_promoted_only_after_threshold():
    store = InMemoryStore()
    assert pr.record_edit("u1", BEFORE, AFTER, store=store) == []
    assert style_rules("u1", store) == []
    assert pr.record_edit("u1", BEFORE + " x", AFTER + " x", store=store) == []
    promoted = pr.record_edit("u1", BEFORE + " y", AFTER + " y", store=store)
    assert "Never say 'passionate'." in promoted
    rules = style_rules("u1", store)
    assert "Never say 'passionate'." in rules and any("opening sentence" in r for r in rules)
    # one-off edits never promote
    assert pr.record_edit("u1", "Hello there. Good stuff.", "Good stuff.", store=store) == []
    assert not any(
        "opening" in c["rule"] and c["count"] > 4 for c in list_memory("u1", store)["candidates"]
    )


def test_outcome_hints_need_samples_and_a_margin():
    store = InMemoryStore()
    job = {"title": "Power BI dashboard", "screening_questions": []}
    good = pr.proposal_features(
        {"cover_letter": "You need a dashboard. " * 10, "evidence_ids": ["a", "b"]}, job
    )
    bad = pr.proposal_features(
        {"cover_letter": "I am a passionate analyst. " * 30, "evidence_ids": []}, job
    )
    out = []
    for _ in range(4):
        out += pr.record_outcome(
            "u2", category="data_analyst", features=good, outcome="replied", store=store
        )
    assert out == [] and outcome_hints("u2", "data_analyst", store) == []  # below min samples
    for _ in range(3):
        out += pr.record_outcome(
            "u2", category="data_analyst", features=bad, outcome="viewed", store=store
        )
    hints = outcome_hints("u2", "data_analyst", store)
    assert hints and any("cites 2plus evidence" in h or "under 200 words" in h for h in hints)
    assert all("passionate" not in h for h in hints)  # hints describe features, never quote drafts


def test_memory_viewer_and_delete():
    store = InMemoryStore()
    for _ in range(3):
        pr.record_edit("u3", BEFORE, AFTER, store=store)
    view = list_memory("u3", store)
    assert view["style"] and view["candidates"]
    key = view["style"][0]["key"]
    assert delete_memory("u3", "style", key, store=store)
    assert key not in [s["key"] for s in list_memory("u3", store)["style"]]
    assert clear_memory("u3", store) > 0
    assert list_memory("u3", store) == {"style": [], "outcome": [], "candidates": []}
