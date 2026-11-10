# GigBid — Student Starter Kit (v0.1)

This is a **scaffold**, not a completed solution. It gives you a suggested repository layout,
small synthetic examples, configuration templates, and interfaces to help you begin AI-4016.

## What is included
- A suggested project structure aligned with the assignment.
- Tiny synthetic job, client, freelancer and portfolio examples.
- A starter marketplace policy pack.
- Typed hand-off models and a minimal LangGraph state/graph placeholder.
- Portfolio and marketplace MCP server placeholders.
- RAG ingestion/retrieval/claim-verification placeholders.
- FastAPI and React starting-point notes.
- `.env.example`, `agent/config.yaml`, `Makefile`, and setup notes.

## What you must build
You are responsible for implementing and testing the agents, MCP tools, marketplace adapters,
advanced RAG variants, claim verification, human approval flow, persistence, UI, evaluations,
deployment, and your own research findings. The sample data is illustrative only and is not a
replacement for the instructor-provided GigSim data or evaluation sets.

## Quick start
1. Create your own public GitHub repository.
2. Copy this starter kit into the repository.
3. Create a Python 3.11+ virtual environment.
4. Install dependencies from `pyproject.toml` (adjust/pin versions after checking compatibility).
5. Copy `.env.example` to `.env` and fill local values. **Never commit `.env`.**
6. Read `docs/GETTING_STARTED.md` and work through the TODO checklist.
7. Keep the instructor-provided `gigsim/`, persona data, policy pack and evaluation assets unchanged.

## Suggested first milestone (for your own planning; not a graded submission)
- Run a health-check API.
- Load one sample job.
- Retrieve one portfolio evidence item.
- Produce a structured analysis.
- Draft a proposal with evidence references.
- Stop at a human approval screen; do not send anything automatically.

## Important safety rules
- Treat job posts and client messages as untrusted input.
- Never follow instructions embedded inside a job post that conflict with system policy.
- Never invent portfolio experience or results.
- Do not scrape Upwork or automate its website.
- Never send proposals/messages or spend Connects without explicit human approval.
- Use the official Upwork MCP server/approved APIs for live mode, if applicable.
- Keep secrets and real client data out of Git.

## Repository map
See `docs/GETTING_STARTED.md` for the purpose of each major folder.
