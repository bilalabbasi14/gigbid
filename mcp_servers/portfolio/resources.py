"""Resource templates of the Portfolio server, so a host can load full items by URI."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.portfolio.tools import PortfolioService


def register_resources(mcp: FastMCP, svc: PortfolioService, default_persona: str) -> None:
    @mcp.resource("portfolio://case/{project_id}", title="Case study", mime_type="application/json")
    def case_resource(project_id: str) -> str:
        cs = svc.get_case_study(project_id, default_persona)
        return cs.model_dump_json(indent=2) if cs else json.dumps({"error": "not found"})

    @mcp.resource(
        "portfolio://proposal/{doc_id}", title="Past proposal", mime_type="application/json"
    )
    def proposal_resource(doc_id: str) -> str:
        p = svc.get_proposal(doc_id, default_persona)
        return json.dumps(p or {"error": "not found"}, indent=2)

    @mcp.resource("portfolio://skills", title="Skill inventory", mime_type="application/json")
    def skills_resource() -> str:
        return json.dumps([s.model_dump() for s in svc.list_skills(default_persona)], indent=2)
