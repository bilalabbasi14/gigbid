"""Portfolio builder (X3) on a local repository with a fake model: facts from code, cited claims,
verification, the review interrupt and saving only approved case studies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.deps import Deps
from agent.graphs import portfolio_builder_graph as pbg
from agent.portfolio_builder.facts import extract_facts
from agent.portfolio_builder.sources import GitHubMCPSource, LocalRepoSource, RepoRef


def make_repo(root: Path) -> None:
    r = root / "churn-api"
    (r / "app").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / "README.md").write_text(
        "# Churn API\n\nPredicts customer churn for a subscription business and serves scores over HTTP.\n",
        encoding="utf-8",
    )
    (r / "requirements.txt").write_text(
        "fastapi==0.110\nscikit-learn>=1.4\npandas\nuvicorn\n", encoding="utf-8"
    )
    (r / "app" / "main.py").write_text(
        "from fastapi import FastAPI\nimport pandas as pd\nfrom sklearn.ensemble import RandomForestClassifier\n\napp = FastAPI()\n\ndef score(df):\n    return 0\n\nclass Model:\n    pass\n",
        encoding="utf-8",
    )
    (r / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (r / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (r / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    empty = root / "notes"
    empty.mkdir()
    (empty / "todo.txt").write_text("x", encoding="utf-8")


async def test_facts_come_from_the_code(tmp_path):
    make_repo(tmp_path)
    facts, profile = await extract_facts(LocalRepoSource(tmp_path), RepoRef(name="churn-api"))
    kinds = {f.kind for f in facts}
    assert {
        "language",
        "dependency",
        "framework",
        "tests",
        "ci",
        "container",
        "readme",
        "import",
    } <= kinds
    assert {"FastAPI", "scikit-learn", "pandas"} <= set(profile["libraries"])
    assert profile["has_tests"] and profile["has_ci"] and profile["has_docker"]
    assert all(re.fullmatch(r"[0-9a-f]{12}", f.fact_id) for f in facts)
    assert any("author's statement" in f.text for f in facts if f.kind == "readme")


class FakeLLM:
    async def __call__(self, node: str, messages: list[Any], **kw: Any) -> AIMessage:
        text = messages[-1].content
        if "Verified facts" in text:
            ids = re.findall(r"\[([0-9a-f]{12})\]", text)
            fw = next(
                m for m in re.finditer(r"\[([0-9a-f]{12})\] \(framework\) uses FastAPI", text)
            )
            body = (
                f"# Churn scoring API\n\n## What it is\nAn HTTP service that predicts customer churn [{ids[-1]}].\n\n"
                f"## How it is built\nBuilt with FastAPI [{fw.group(1)}] and a scikit-learn model.\n\n"
                "## Engineering practice\nIt served 2 million users a day.\n\n## Skills shown\nFastAPI, scikit-learn"
            )
            return AIMessage(
                content=body,
                usage_metadata={"input_tokens": 300, "output_tokens": 120, "total_tokens": 420},
            )
        if text.startswith("Proposal:") and "Flagged claims" not in text:
            return AIMessage(
                content=json.dumps(
                    {
                        "claims": [
                            {
                                "text": "Built with FastAPI",
                                "cited_evidence_ids": re.findall(r"\[([0-9a-f]{12})\]", text)[1:2],
                            },
                            {"text": "It served 2 million users a day.", "cited_evidence_ids": []},
                        ]
                    }
                )
            )
        if "Claim c1" in text:
            return AIMessage(
                content=json.dumps(
                    {
                        "labels": [
                            {"claim_id": "c1", "label": "supported"},
                            {"claim_id": "c2", "label": "unsupported"},
                        ]
                    }
                )
            )
        if "Flagged claims" in text:
            m = re.search(r"Proposal:\n(.*)\n\nFlagged claims", text, re.S)
            return AIMessage(
                content=(m.group(1) if m else "").replace("It served 2 million users a day.", "")
            )
        return AIMessage(content="{}")


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setattr(pbg, "PERSONAS_ROOT", tmp_path / "personas")
    make_repo(tmp_path / "src")
    return pbg.build_graph(
        Deps(invoke=FakeLLM(), use_reranker=False), checkpointer=InMemorySaver(), reindex=False
    ), tmp_path


async def test_build_review_and_save_only_approved(graph):
    g, tmp = graph
    cfg = pbg.builder_config("pb1")
    out = await g.ainvoke(
        pbg.initial_builder_state(
            thread_id="pb1",
            owner="me",
            persona_key="user_x",
            source_kind="local",
            local_root=str(tmp / "src"),
        ),
        cfg,
    )
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "portfolio"
    drafts = {d["repo"]: d for d in payload["drafts"]}
    assert "churn-api" in drafts and "notes" in {s["repo"] for s in payload["skipped"]}
    d = drafts["churn-api"]
    assert "2 million" not in d["markdown"], (
        "unsupported invented metric must be removed by verification"
    )
    assert (
        d["verification"]["before"]["unsupported"] == 1
        and d["verification"]["unsupported_rate_after"] == 0.0
    )
    out = await g.ainvoke(Command(resume={"decisions": {"churn-api": {"action": "approve"}}}), cfg)
    assert out["status"] == "submitted" and out["saved"][0]["repo"] == "churn-api"
    pdir = tmp / "personas" / "user_x"
    cs = (pdir / "case_studies" / "gh_churn-api.md").read_text(encoding="utf-8")
    assert "verified: true" in cs and "source: portfolio_builder" in cs
    proj = json.loads((pdir / "projects.json").read_text(encoding="utf-8"))
    assert proj[0]["verified"] and "FastAPI" in proj[0]["libraries"]
    assert (pdir / "repos" / "churn-api" / "FACTS.json").exists()


async def test_reject_saves_nothing(graph):
    g, tmp = graph
    cfg = pbg.builder_config("pb2")
    await g.ainvoke(
        pbg.initial_builder_state(
            thread_id="pb2",
            owner="me",
            persona_key="user_y",
            source_kind="local",
            local_root=str(tmp / "src"),
        ),
        cfg,
    )
    out = await g.ainvoke(Command(resume={"decisions": {"churn-api": {"action": "reject"}}}), cfg)
    assert (
        out["status"] == "rejected"
        and not (tmp / "personas" / "user_y" / "case_studies" / "gh_churn-api.md").exists()
    )


async def test_github_source_parses_mcp_outputs():
    calls = []

    async def call(name: str, **args: Any) -> Any:
        calls.append(name)
        if name == "search_repositories":
            return json.dumps(
                {
                    "items": [
                        {
                            "name": "a",
                            "description": "x",
                            "fork": False,
                            "updated_at": "2026-01-01",
                            "stargazers_count": 3,
                        },
                        {"name": "b", "fork": True},
                    ]
                }
            )
        if name == "get_repository_tree":
            return {
                "tree": [
                    {"path": "README.md", "type": "blob"},
                    {"path": "src", "type": "tree"},
                    {"path": "node_modules/x.js", "type": "blob"},
                ]
            }
        if name == "get_file_contents":
            return [{"type": "text", "text": "hello"}]
        return [{"sha": "1", "commit": {"author": {"date": "2025-01-02T00:00:00Z", "name": "me"}}}]

    src = GitHubMCPSource(call, "me")
    repos = await src.list_repos(5)
    assert [r.name for r in repos] == ["a"]
    assert await src.tree("a") == ["README.md"]
    assert await src.read("a", "README.md") == "hello"
    assert (await src.commits("a")).count == 1
