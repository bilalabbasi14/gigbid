# gigbid-portfolio-mcp

An MCP server that lets an AI assistant search **your** freelance portfolio for evidence before it
writes anything about you. Every result carries the file it came from, so a proposal, screening
answer or cover letter can cite real work instead of inventing experience.

It is the stand-alone version of the Portfolio server in [GigBid](https://github.com/bilalabbasi14/gigbid):
read-only, no database, no GPU, no API keys. Point it at a folder and plug it into Claude Desktop,
Cursor or any MCP host.

## Install and run

```bash
# straight from GitHub (no install step)
uvx --from "git+https://github.com/bilalabbasi14/gigbid#subdirectory=packages/gigbid-portfolio-mcp" gigbid-portfolio-mcp --portfolio ~/my-portfolio

# or, once published to PyPI
uvx gigbid-portfolio-mcp --portfolio ~/my-portfolio
```

Add `--http` to serve streamable HTTP on `127.0.0.1:8101/mcp` instead of stdio.

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "portfolio": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bilalabbasi14/gigbid#subdirectory=packages/gigbid-portfolio-mcp", "gigbid-portfolio-mcp", "--portfolio", "/absolute/path/to/my-portfolio"]
    }
  }
}
```

## Your portfolio folder

Any folder of `.md`, `.txt` and `.pdf` files works: each file is one item, and optional front
matter (`skills: [...]`, `year: 2024`) improves search. For richer answers use the GigBid layout:

```text
my-portfolio/
├── cv.pdf                      # or cv.md
├── projects.json               # [{"id": "p01", "name": "...", "year": 2024, "skills": [...], "libraries": [...]}]
├── case_studies/*.md           # front matter: project_id, year, client_industry, skills, libraries
├── repos/<name>/README.md + code, with a .project_id file
├── reviews.jsonl               # {"project_id": "p01", "rating": 5, "text": "..."}
└── proposals.jsonl             # {"cover_letter": "...", "outcome": "won|replied|ignored", "project_ids": ["p01"]}
```

## What it exposes

| Kind | Name | What it does |
|---|---|---|
| Tool | `search_evidence(requirement, k, types, outcome)` | Ranked items that support one requirement, with type, source file, date and past-proposal outcome |
| Tool | `get_case_study(id)` | Everything about one project: case study, README, code files, reviews |
| Tool | `list_skills()` | Every evidenced skill with project ids, evidence count and winning proposals |
| Resource | `portfolio://item/{item_id}`, `portfolio://case/{project_id}`, `portfolio://skills` | Full items for the host to load |
| Prompt | Answer a screening question · Summarise my fit for a job · Draft a case study | Ready-made workflows that only use returned evidence |

All tools are annotated read-only, idempotent and closed-world. Search is BM25 over
paragraph-sized chunks (exact library names such as "dbt" or "Celery" match precisely). Job posts
passed to the prompts are marked as untrusted data.

## Development

```bash
cd packages/gigbid-portfolio-mcp
uv run --extra dev pytest
npx @modelcontextprotocol/inspector uvx --from . gigbid-portfolio-mcp --portfolio ../../data/personas/ai_ml
```

MIT licence.
