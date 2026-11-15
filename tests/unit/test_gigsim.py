"""GigSim simulator behaviour: auth, search, proposals, idempotency, dry-run, connects, limits."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["GIGSIM_DB_PATH"] = ":memory:"
os.environ["GIGSIM_CHAOS_RATE"] = "0"
os.environ["GIGSIM_RATE_PER_MINUTE"] = "1000"
os.environ["GIGSIM_CLIENT_MODE"] = "rules"
os.environ["GIGSIM_ACCOUNTS"] = "dev-token:freelancer_dev:Dev Freelancer"

from gigsim import app as gigsim_app  # noqa: E402

H = {"Authorization": "Bearer dev-token"}


@pytest.fixture(scope="module")
def client():
    with TestClient(gigsim_app.app) as c:
        yield c


def test_requires_bearer(client):
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_seeded_and_searchable(client):
    r = client.get("/jobs", headers=H, params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 200 and len(body["items"]) == 5
    job = body["items"][0]
    assert {
        "job_id",
        "title",
        "description",
        "skills",
        "connects_cost",
        "screening_questions",
    } <= job.keys()
    assert "hidden_prefs" not in job and "persona_hint" not in job
    r = client.get(f"/jobs/{job['job_id']}", headers=H)
    assert r.status_code == 200 and r.json()["client"]["client_id"]
    c = client.get(f"/clients/{job['client_id']}", headers=H).json()
    assert "hidden_prefs" not in c and "past_jobs" in c


def _open_job(client):
    return client.get("/jobs", headers=H, params={"limit": 1}).json()["items"][0]


def test_dry_run_then_submit_is_idempotent(client):
    job = _open_job(client)
    before = client.get("/me/connects", headers=H).json()["balance"]
    payload = {
        "job_id": job["job_id"],
        "cover_letter": "Hi, I built a similar "
        + job["title"]
        + " pipeline last year with "
        + ", ".join(job["skills"][:2])
        + ". Happy to walk you through it. " * 2,
        "bid_amount": 400.0 if job["payment_type"] == "fixed" else 30.0,
        "bid_type": job["payment_type"],
        "screening_answers": ["Answer " * 10 for _ in job["screening_questions"]],
        "idempotency_key": "test-key-0001",
        "dry_run": True,
    }
    r = client.post("/proposals", headers=H, json=payload)
    assert r.status_code == 201 and r.json()["dry_run"] is True
    assert r.json()["would_send"]["connects_cost"] == job["connects_cost"]
    assert client.get("/me/connects", headers=H).json()["balance"] == before

    payload["dry_run"] = False
    r1 = client.post("/proposals", headers=H, json=payload)
    assert r1.status_code == 201 and r1.json()["proposal"]["status"] in {
        "submitted",
        "viewed",
        "replied",
        "interview",
        "hired",
        "lost",
    }
    after = client.get("/me/connects", headers=H).json()["balance"]
    assert after == before - job["connects_cost"]

    r2 = client.post("/proposals", headers=H, json=payload)  # retry with same key
    assert r2.status_code == 201 and r2.json()["idempotent_replay"] is True
    assert client.get("/me/connects", headers=H).json()["balance"] == after  # not charged twice

    payload["idempotency_key"] = "test-key-0002"
    assert client.post("/proposals", headers=H, json=payload).status_code == 409  # already applied


def test_wrong_bid_type_rejected(client):
    job = _open_job(client)
    other = "hourly" if job["payment_type"] == "fixed" else "fixed"
    r = client.post(
        "/proposals",
        headers=H,
        json={
            "job_id": job["job_id"],
            "cover_letter": "x" * 60,
            "bid_amount": 10,
            "bid_type": other,
            "idempotency_key": "test-key-0003",
        },
    )
    assert r.status_code == 422


def test_insufficient_connects(client):
    client.post("/admin/connects", params={"freelancer_id": "freelancer_dev", "balance": 1})
    jobs = client.get("/jobs", headers=H, params={"limit": 5}).json()["items"]
    job = jobs[-1]
    r = client.post(
        "/proposals",
        headers=H,
        json={
            "job_id": job["job_id"],
            "cover_letter": "y" * 60,
            "bid_amount": 10,
            "bid_type": job["payment_type"],
            "idempotency_key": "test-key-0004",
        },
    )
    assert r.status_code == 402
    client.post("/admin/connects", params={"freelancer_id": "freelancer_dev", "balance": 200})


def test_tick_releases_pooled_jobs(client):
    before = client.get("/admin/stats").json()["jobs"]
    r = client.post("/admin/tick", params={"n": 3, "persona": "ai_ml"})
    assert len(r.json()["released"]) == 3
    after = client.get("/admin/stats").json()["jobs"]
    assert after["open"] == before["open"] + 3


def test_messages_round_trip(client):
    threads = client.get("/threads", headers=H).json()["items"]
    if not threads:
        pytest.skip("deterministic client did not reply to the test proposal")
    t = threads[0]
    msgs = client.get("/messages", headers=H, params={"thread_id": t["thread_id"]}).json()["items"]
    assert msgs and msgs[0]["sender"] == "client"
    r = client.post(
        "/messages",
        headers=H,
        json={
            "thread_id": t["thread_id"],
            "body": "Thanks! I am available for a call tomorrow.",
            "idempotency_key": "test-msg-0001",
        },
    )
    assert r.status_code == 201
    again = client.post(
        "/messages",
        headers=H,
        json={
            "thread_id": t["thread_id"],
            "body": "Thanks! I am available for a call tomorrow.",
            "idempotency_key": "test-msg-0001",
        },
    )
    assert again.json()["idempotent_replay"] is True


def test_rate_limit_shape():
    from gigsim.ratelimit import TokenBucket

    b = TokenBucket(rate_per_minute=2, burst=2)
    assert b.take("k")[0] and b.take("k")[0]
    ok, retry = b.take("k")
    assert not ok and retry > 0


# ---------- LLM-driven clients ----------
from gigsim import client_llm  # noqa: E402
from gigsim import clients as sim_clients  # noqa: E402

PREFS = {"must_have_skills": ["Django"], "budget_ceiling": 1000, "reply_warmth": 0.8}
JOB = {"job_id": "j1", "title": "Django API", "description": "Build a Django REST API"}


def test_llm_interest_moves_the_reply_probability():
    letter = "Your Django REST API needs auth and tests; I would start with the models."
    cold = sim_clients.decide(JOB, PREFS, "k", letter, 500, [], llm_view={"interest": 0.0})
    warm = sim_clients.decide(JOB, PREFS, "k", letter, 500, [], llm_view={"interest": 1.0})
    rules = sim_clients.decide(JOB, PREFS, "k", letter, 500, [])
    assert (
        cold["breakdown"]["p_reply"] < rules["breakdown"]["p_reply"] < warm["breakdown"]["p_reply"]
    )
    assert warm["breakdown"]["mode"] == "llm" and rules["breakdown"]["mode"] == "rules"
    assert warm["breakdown"]["rule_score"] == rules["breakdown"]["score"]


def test_scam_posters_never_reply_even_if_the_model_likes_the_letter():
    prefs = {**PREFS, "never_replies": True}
    d = sim_clients.decide(JOB, prefs, "k", "Great letter", 500, [], llm_view={"interest": 1.0})
    assert d["breakdown"]["p_reply"] == 0.0 and d["message"] is None


def test_llm_mode_decides_in_the_background(client, monkeypatch):
    monkeypatch.setenv("GIGSIM_CLIENT_MODE", "llm")
    monkeypatch.setenv("GIGSIM_DECIDE_INLINE", "1")
    seen = []

    def fake_judge(job, prefs, letter, bid, answers):
        seen.append(job["job_id"])
        return {"interest": 0.9, "concerns": [], "reply": "Sounds good, when can you start?"}

    monkeypatch.setattr(client_llm, "judge", fake_judge)
    applied = {p["job_id"] for p in client.get("/proposals", headers=H).json()["items"]}
    jobs = client.get("/jobs", headers=H, params={"limit": 50}).json()["items"]
    job = next(j for j in jobs if j["job_id"] not in applied)
    r = client.post(
        "/proposals",
        headers=H,
        json={
            "job_id": job["job_id"],
            "cover_letter": f"Your {job['title']} needs a clear first milestone.",
            "bid_amount": 400.0 if job["payment_type"] == "fixed" else 30.0,
            "bid_type": job["payment_type"],
            "screening_answers": [
                "An answer of reasonable length." for _ in job["screening_questions"]
            ],
            "idempotency_key": "llm-mode-0001",
        },
    )
    assert r.status_code == 201, r.text
    first = r.json()["proposal"]
    assert first["status"] == "submitted" and first["decided"] is False
    after = client.get(f"/proposals/{first['proposal_id']}", headers=H).json()
    assert after["decided"] is True and seen == [job["job_id"]]


def test_client_llm_parses_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGSIM_LLM_CACHE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(client_llm, "_CACHE", None)
    calls = []

    def fake_chat(system, user, timeout):
        calls.append(user)
        return 'Sure: {"interest": 1.7, "concerns": ["a", "b", "c", "d"], "reply": "Hi"}'

    monkeypatch.setattr(client_llm, "_chat", fake_chat)
    first = client_llm.judge(JOB, PREFS, "letter", 100.0, [])
    again = client_llm.judge(JOB, PREFS, "letter", 100.0, [])
    assert first["interest"] == 1.0 and len(first["concerns"]) == 3
    assert again["cached"] is True and len(calls) == 1
    assert client_llm.parse("no json here") is None


def test_two_accounts_may_use_the_same_idempotency_key(client):
    client.post(
        "/admin/accounts",
        params={"api_key": "second-token", "freelancer_id": "fl_second", "connects": 500},
    )
    h2 = {"Authorization": "Bearer second-token"}
    applied = {p["job_id"] for p in client.get("/proposals", headers=H).json()["items"]}
    job = next(
        j
        for j in client.get("/jobs", headers=H, params={"limit": 50}).json()["items"]
        if j["job_id"] not in applied
    )
    body = {
        "job_id": job["job_id"],
        "cover_letter": f"Your {job['title']} needs a clear first milestone and weekly demos.",
        "bid_amount": 400.0 if job["payment_type"] == "fixed" else 30.0,
        "bid_type": job["payment_type"],
        "screening_answers": [
            "An answer of reasonable length." for _ in job["screening_questions"]
        ],
        "idempotency_key": "shared-key-0001",
    }
    assert client.post("/proposals", headers=H, json=body).status_code == 201
    assert client.post("/proposals", headers=h2, json=body).status_code == 201
    assert client.post("/proposals", headers=h2, json=body).json()["idempotent_replay"] is True
