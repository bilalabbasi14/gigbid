"""Portfolio MCP server (read-only): evidence search, case studies, skills, resources and prompts.

Run locally:   uv run python -m mcp_servers.portfolio.server            (stdio, for Claude Desktop / Cursor)
               uv run python -m mcp_servers.portfolio.server --http     (streamable HTTP on :8101/mcp)
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common.auth import make_token_verifier, token_auth_settings
from mcp_servers.portfolio.prompts import register_prompts
from mcp_servers.portfolio.resources import register_resources
from mcp_servers.portfolio.tools import (
    CaseStudy,
    PortfolioService,
    SearchEvidenceResult,
    SearchFilters,
    SkillEntry,
)

DEFAULT_PERSONA = os.environ.get("PORTFOLIO_DEFAULT_PERSONA", "ai_ml")
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def build_server(service: PortfolioService | None = None, *, http_auth: bool = False) -> FastMCP:
    svc = service or PortfolioService()
    kwargs: dict[str, Any] = {}
    if http_auth:
        kwargs["token_verifier"] = make_token_verifier()
        kwargs["auth"] = token_auth_settings()
    mcp = FastMCP(
        "gigbid-portfolio",
        instructions="Read-only access to a freelancer's portfolio: search evidence for a requirement, open a full case study, list skills. Every item carries a source path so claims can be verified.",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORTFOLIO_PORT", "8101")),
        streamable_http_path="/mcp",
        **kwargs,
    )

    @mcp.tool(annotations=READ_ONLY, title="Search portfolio evidence")
    def search_evidence(
        requirement: str = Field(
            description="One requirement from a job post, e.g. 'build a RAG chatbot over PDFs with citation'",
            min_length=3,
            max_length=1000,
        ),
        k: int = Field(default=5, ge=1, le=20, description="How many evidence items to return"),
        filters: SearchFilters | None = Field(
            default=None, description="Optional metadata filters"
        ),
        persona: str = Field(
            default=DEFAULT_PERSONA, description="Which freelancer profile to search"
        ),
    ) -> SearchEvidenceResult:
        """Find portfolio evidence (case studies, code, reviews, past proposals) that supports one requirement.
        Returns ranked items with type, source path, date and past-proposal outcome. Use one call per requirement."""
        return svc.search_evidence(requirement, persona, k=k, filters=filters)

    @mcp.tool(annotations=READ_ONLY, title="Get a full case study")
    def get_case_study(
        id: str = Field(
            description="Project id such as p03 (from search_evidence results)", pattern=r"^p\d{2}$"
        ),
        persona: str = Field(default=DEFAULT_PERSONA),
    ) -> CaseStudy:
        """Return everything the portfolio holds about one project: metadata, the case study text, README, code file list, reviews and proposals that cited it."""
        cs = svc.get_case_study(id, persona)
        if cs is None:
            raise ValueError(f"unknown project id {id!r} for persona {persona!r}")
        return cs

    @mcp.tool(annotations=READ_ONLY, title="List skills with evidence counts")
    def list_skills(persona: str = Field(default=DEFAULT_PERSONA)) -> list[SkillEntry]:
        """List every skill and library the portfolio evidences, with project ids, evidence count, last year used and how many winning proposals mention it."""
        return svc.list_skills(persona)

    register_resources(mcp, svc, DEFAULT_PERSONA)
    register_prompts(mcp)
    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--http",
        action="store_true",
        help="serve streamable HTTP with bearer auth instead of stdio",
    )
    args = ap.parse_args()
    server = build_server(http_auth=args.http)
    server.run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    main()
