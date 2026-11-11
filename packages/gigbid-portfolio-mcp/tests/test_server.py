from __future__ import annotations

import json
from pathlib import Path

import pytest
from gigbid_portfolio_mcp.corpus import Portfolio
from gigbid_portfolio_mcp.server import build_server
from mcp.shared.memory import create_connected_server_and_client_session

GIGBID_PERSONA = Path(__file__).resolve().parents[3] / "data" / "personas" / "ai_ml"


@pytest.fixture
def plain_folder(tmp_path: Path) -> Path:
    (tmp_path / "churn.md").write_text(
        "---\nskills: [Python, scikit-learn]\nyear: 2024\n---\n# Churn model for a fintech\n\nBuilt a churn classifier with scikit-learn; recall rose from 0.61 to 0.78.\n",
        encoding="utf-8",
    )
    (tmp_path / "dashboards.txt").write_text(
        "Power BI sales dashboards for a retailer, refreshed nightly from SQL Server.",
        encoding="utf-8",
    )
    return tmp_path


async def test_plain_folder_search_and_tools(plain_folder: Path):
    server = build_server(Portfolio(plain_folder))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"search_evidence", "get_case_study", "list_skills"}
        assert all(t.annotations.readOnlyHint for t in tools.values())
        r = await client.call_tool(
            "search_evidence", {"requirement": "scikit-learn churn classifier", "k": 2}
        )
        items = r.structuredContent["items"]
        assert items[0]["title"] == "Churn model for a fintech" and items[0]["source"] == "churn.md"
        r = await client.call_tool("search_evidence", {"requirement": "power bi dashboards"})
        assert r.structuredContent["items"][0]["source"] == "dashboards.txt"
        skills = (await client.call_tool("list_skills", {})).structuredContent["result"]
        assert {s["skill"] for s in skills} >= {"Python", "scikit-learn"}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        assert prompts == {"answer_screening_question", "summarise_fit", "draft_case_study"}


@pytest.mark.skipif(
    not (GIGBID_PERSONA / "projects.json").exists(), reason="GigBid persona corpus not present"
)
async def test_gigbid_layout_projects_and_resources():
    p = Portfolio(GIGBID_PERSONA)
    assert any(it.type == "code" for it in p.items) and any(
        it.type == "proposal" and it.outcome for it in p.items
    )
    server = build_server(p)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        pid = next(iter(p.projects))
        cs = (await client.call_tool("get_case_study", {"id": pid})).structuredContent
        assert cs["project_id"] == pid and cs["case_study_markdown"]
        r = await client.read_resource(f"portfolio://case/{pid}")
        assert json.loads(r.contents[0].text)["project_id"] == pid
        won = (
            await client.call_tool(
                "search_evidence",
                {"requirement": "machine learning", "types": ["proposal"], "outcome": "won"},
            )
        ).structuredContent["items"]
        assert all(i["outcome"] == "won" and i["type"] == "proposal" for i in won)
        bad = await client.call_tool("get_case_study", {"id": "nope"})
        assert bad.isError
