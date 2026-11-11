"""Crash-and-resume drill (C6) against the real API process, Postgres checkpointer and GigSim.

  1. start the API, sign in, scout, analyse one job and wait until it waits for approval
  2. kill the API process (hard) and start a new one
  3. the pending approval is still there; approve it through the API
  4. GigSim shows exactly one proposal for that job; approving again is refused (409)
  5. replay the run from an earlier checkpoint into a new thread (time travel)

Writes evals/results/durability_drill.json. Needs Postgres (docker compose), GigSim on :8081 and a
model key. Uses a dedicated user, so it never touches the reviewer's data.

  uv run python -m scripts.durability_drill [--port 8010] [--query "machine learning"]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any

import httpx

from agent.settings import ROOT, env


def start_api(port: int) -> subprocess.Popen[bytes]:
    e = {
        **os.environ,
        "APP_ENV": "development",
        "GIGBID_WARM_MODELS": "1",
        "LANGSMITH_TRACING": os.environ.get("LANGSMITH_TRACING", "false"),
    }
    log = open(ROOT / "data/processed/durability_api.log", "ab")  # noqa: SIM115 - kept open for the child
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.api.serve",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=e,
        stdout=log,
        stderr=log,
    )


def wait_up(base: str, timeout: float = 300) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"{base}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError("API did not start")


def gigsim_proposals_for(job_id: str, token: str) -> list[dict[str, Any]]:
    r = httpx.get(
        f"{env().gigsim_base_url}/proposals",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return [p for p in r.json()["items"] if p["job_id"] == job_id]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--query", default="machine learning")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    log: dict[str, Any] = {"steps": []}

    def note(step: str, **kw: Any) -> None:
        log["steps"].append({"t": round(time.time() - t_start, 1), "step": step, **kw})
        print(f"[{log['steps'][-1]['t']:7.1f}s] {step} {json.dumps(kw, default=str)[:200]}")

    t_start = time.time()
    api = start_api(args.port)
    try:
        wait_up(base)
        persistence = httpx.get(f"{base}/health", timeout=10).json().get("persistence")
        note("api started", pid=api.pid, persistence=persistence)
        if persistence != "postgres":
            raise SystemExit(
                "the API is not using the Postgres checkpointer; the drill is meaningless"
            )
        c = httpx.Client(base_url=base, timeout=60)
        email = f"drill-{uuid.uuid4().hex[:6]}@gigbid.local"
        c.post(
            "/auth/register",
            json={"email": email, "password": "drill-password", "persona": "ai_ml"},
        ).raise_for_status()
        c.put(
            "/settings",
            json={
                "onboarded": True,
                "hourly_rate": 55,
                "hourly_floor": 20,
                "min_project_budget": 50,
                "weekly_connects_budget": 400,
            },
        ).raise_for_status()
        sc = c.post("/jobs/scout", json={"query": args.query, "limit": 10}).json()
        note("scouted", **sc)
        jobs = c.get("/jobs").json()["items"]
        thread = None
        for j in jobs:  # analyse until one job reaches the approval gate
            run = c.post(f"/jobs/{j['job_id']}/analyse").json()
            for _ in range(240):
                st = c.get(f"/runs/{run['thread_id']}").json()["status"]
                if st not in ("queued", "running"):
                    break
                time.sleep(3)
            note("analysed", job_id=j["job_id"], status=st)
            if st == "awaiting_approval":
                thread, job_id = run["thread_id"], j["job_id"]
                break
        if not thread:
            raise SystemExit("no job reached approval; try another --query")
        before = c.get(f"/approvals/{thread}").json()
        note("waiting for approval", thread=thread, connects=before["proposal"]["connects_cost"])

        api.kill()  # hard crash, no graceful shutdown
        api.wait(timeout=30)
        note("api killed")
        api = start_api(args.port)
        wait_up(base)
        note("api restarted", pid=api.pid)
        c = httpx.Client(base_url=base, timeout=120, cookies=c.cookies)
        pending = c.get("/approvals").json()["items"]
        survived = any(p["thread_id"] == thread for p in pending)
        note("pending approval after restart", survived=survived)

        res = c.post(f"/approvals/{thread}", json={"action": "approve"}).json()
        note(
            "approved",
            status=res.get("status"),
            proposal_id=(res.get("submission") or {}).get("proposal_id"),
        )
        again = c.post(f"/approvals/{thread}", json={"action": "approve"})
        note("second approve", http_status=again.status_code)
        props = gigsim_proposals_for(job_id, env().gigsim_api_token)
        note("gigsim proposals for job", count=len(props))

        cps = c.get(f"/runs/{thread}").json()["checkpoints"]
        target = next((cp for cp in cps if "writer" in (cp.get("next") or [])), None)
        replay = (
            c.post(f"/runs/{thread}/replay", json={"checkpoint_id": target["checkpoint_id"]}).json()
            if target
            else None
        )
        note(
            "replay from the writer checkpoint",
            new_thread=(replay or {}).get("thread_id"),
            checkpoints=len(cps),
        )

        log.update(
            {
                "thread_id": thread,
                "job_id": job_id,
                "approval_survived_restart": survived,
                "final_status": res.get("status"),
                "second_approve_http": again.status_code,
                "gigsim_proposals_for_job": len(props),
                "exactly_once": len(props) == 1
                and res.get("status") == "submitted"
                and again.status_code == 409,
                "replay_thread": (replay or {}).get("thread_id"),
            }
        )
    finally:
        api.kill()
    out = ROOT / "evals/results/durability_drill.json"
    out.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    print(f"exactly once: {log.get('exactly_once')} -> {out}")


if __name__ == "__main__":
    main()
