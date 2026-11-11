"""Portfolio MCP server through an in-memory client session (no HTTP, no models, no DB)."""

from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.portfolio.server import build_server
from mcp_servers.portfolio.tools import (
    CaseStudy,
    EvidenceItem,
    PortfolioService,
    SearchEvidenceResult,
    SkillEntry,
)


class FakeService(PortfolioService):
    def __init__(self) -> None:  # no resources
        self.variant = "fake"

    def search_evidence(self, requirement, persona, k=5, filters=None):  # type: ignore[override]
        items = [
            EvidenceItem(
                evidence_id=f"ev{i}",
                type="case_study",
                title=f"Project {i}",
                project_id=f"p0{i}",
                excerpt=f"Evidence for {requirement}",
                source="data/personas/x/case_studies/cs_01.md",
                date=2023,
                outcome=None,
                skills=["Python"],
                score=0.9 - i / 10,
                scores={"dense": 0.9},
            )
            for i in range(1, k + 1)
        ]
        if filters and filters.doc_types:
            items = [i for i in items if i.type in filters.doc_types]
        return SearchEvidenceResult(
            requirement=requirement, persona=persona, variant=self.variant, items=items
        )

    def get_case_study(self, project_id, persona):  # type: ignore[override]
        if project_id != "p01":
            return None
        return CaseStudy(
            project_id="p01",
            persona=persona,
            name="Churn model",
            year=2023,
            client_industry="fintech",
            skills=["Python"],
            libraries=["scikit-learn"],
            outcome_metrics=["AUC 0.91"],
            case_study_markdown="# Churn",
            readme_markdown=None,
            code_files=[],
            reviews=[],
            proposals_citing=[],
        )

    def list_skills(self, persona):  # type: ignore[override]
        return [
            SkillEntry(
                skill="Python",
                projects=["p01"],
                evidence_count=3,
                last_used_year=2023,
                won_proposals=1,
            )
        ]

    def get_proposal(self, doc_id, persona):  # type: ignore[override]
        return (
            {"doc_id": doc_id, "cover_letter": "Hi", "outcome": "won"} if doc_id == "abc" else None
        )


@pytest.fixture
def server():
    return build_server(FakeService())


async def test_tools_schemas_and_annotations(server):
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = (await client.list_tools()).tools
        names = {t.name for t in tools}
        assert names == {"search_evidence", "get_case_study", "list_skills"}
        for t in tools:
            assert (
                t.annotations
                and t.annotations.readOnlyHint is True
                and t.annotations.destructiveHint is False
            )
            assert t.inputSchema["type"] == "object"
            assert t.outputSchema is not None
        se = next(t for t in tools if t.name == "search_evidence")
        assert {"requirement", "k", "filters", "persona"} <= set(se.inputSchema["properties"])
        assert se.inputSchema["properties"]["k"]["maximum"] == 20


async def test_search_evidence_structured_output(server):
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        res = await client.call_tool(
            "search_evidence", {"requirement": "build a RAG chatbot", "k": 3}
        )
        assert not res.isError
        assert res.structuredContent["items"][0]["evidence_id"] == "ev1"
        assert len(res.structuredContent["items"]) == 3
        res = await client.call_tool("search_evidence", {"requirement": "x", "k": 99})
        assert res.isError  # constraint k <= 20 enforced by schema


async def test_case_study_and_skills(server):
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        res = await client.call_tool("get_case_study", {"id": "p01"})
        assert res.structuredContent["name"] == "Churn model"
        res = await client.call_tool("get_case_study", {"id": "p99"})
        assert res.isError and "unknown project" in res.content[0].text
        res = await client.call_tool("list_skills", {})
        assert res.structuredContent["result"][0]["skill"] == "Python"


async def test_resources_and_prompts(server):
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        templates = (await client.list_resource_templates()).resourceTemplates
        uris = {t.uriTemplate for t in templates}
        assert {"portfolio://case/{project_id}", "portfolio://proposal/{doc_id}"} <= uris
        r = await client.read_resource("portfolio://case/p01")
        assert json.loads(r.contents[0].text)["project_id"] == "p01"
        r = await client.read_resource("portfolio://proposal/abc")
        assert json.loads(r.contents[0].text)["outcome"] == "won"
        prompts = (await client.list_prompts()).prompts
        assert {"answer_screening_question", "summarise_fit", "draft_case_study"} <= {
            p.name for p in prompts
        }
        p = await client.get_prompt(
            "answer_screening_question",
            {"question": "How do you evaluate an imbalanced classifier?"},
        )
        assert "search_evidence" in p.messages[0].content.text
