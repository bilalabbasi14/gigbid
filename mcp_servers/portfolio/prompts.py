"""Prompt templates a freelancer would actually pick in an MCP host. Texts live in
agent/prompts/mcp_portfolio.md (versioned with every other prompt)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Message, UserMessage

from agent.prompts import load_sections


def register_prompts(mcp: FastMCP) -> None:
    texts = load_sections("mcp_portfolio")

    @mcp.prompt(title="Answer a screening question from my portfolio")
    def answer_screening_question(question: str, job_title: str = "") -> list[Message]:
        clause = f" for the job {job_title}" if job_title else ""
        return [
            UserMessage(
                texts["answer_screening_question"].format(question=question, job_clause=clause)
            )
        ]

    @mcp.prompt(title="Summarise my fit for a job")
    def summarise_fit(job_description: str) -> list[Message]:
        return [UserMessage(texts["summarise_fit"].format(job_description=job_description))]

    @mcp.prompt(title="Draft a case study from a project id")
    def draft_case_study(project_id: str) -> list[Message]:
        return [UserMessage(texts["draft_case_study"].format(project_id=project_id))]
