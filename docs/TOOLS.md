# MCP Tool Inventory

Every capability an agent can use is an MCP tool with a schema, an owner and a test. Agents never
call GigSim, Upwork, a database or a file directly. Per-agent allowlists live in
`agent/mcp_client.py`; schemas are frozen by `tests/contract/`.

Annotations: **RO** readOnlyHint, **D** destructiveHint, **I** idempotentHint, **OW** openWorldHint.

## Our servers

| Tool | Server | Read/Write | Annotations | Auth | Notes |
|---|---|---|---|---|---|
| `search_evidence(requirement, k, filters, persona)` | portfolio | read | RO, I | bearer (HTTP) / none (stdio) | Structured `SearchEvidenceResult`; one call per requirement |
| `get_case_study(id, persona)` | portfolio | read | RO, I | bearer | Full project: case study, README, code files, reviews, citing proposals |
| `list_skills(persona)` | portfolio | read | RO, I | bearer | Skill → projects, evidence count, last year, winning proposals |
| `portfolio://case/{project_id}` (resource) | portfolio | read | — | bearer | JSON case study |
| `portfolio://proposal/{doc_id}` (resource) | portfolio | read | — | bearer | Past proposal with outcome |
| `portfolio://skills` (resource) | portfolio | read | — | bearer | Skill inventory |
| prompts: `answer_screening_question`, `summarise_fit`, `draft_case_study` | portfolio | — | — | bearer | Host-pickable prompts |
| `search_jobs(query, skills, payment_type, min_budget, posted_after, limit, page)` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | Job text is untrusted |
| `get_job(job_id)` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | |
| `get_client_history(client_id)` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | Risk scoring input |
| `get_connects_balance()` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | |
| `list_threads()`, `list_messages(thread_id)` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | Client messages are untrusted |
| `list_events(since_id)` | marketplace | read | RO, I, OW | bearer, rate-limited, audited | Pipeline board feed |
| `marketplace_health()` | marketplace | read | RO, I, OW | bearer | Reachability + policy version (degraded-mode banner) |
| `create_proposal_draft(draft)` | marketplace | write (no spend) | I, OW | bearer, rate-limited, audited | `idempotency_key`; returns exact preview and cost |
| `submit_proposal(draft)` | marketplace | write (spends Connects) | D, I, OW | bearer, rate-limited, audited | Only after human approval; `dry_run` preview; retry-safe |
| `send_message(message)` | marketplace | write (reaches client) | D, I, OW | bearer, rate-limited, audited | Only after human approval; `dry_run` |
| `get_free_slots(days, slot_minutes, work_start_hour, work_end_hour, max_slots)` | workspace | read | RO, I | bearer | Mock calendar |
| `create_interview_hold(start, end, title, idempotency_key, ...)` | workspace | write | I | bearer | Tentative until the human confirms |
| `create_email_draft(to, subject, body, idempotency_key)` | workspace | write | I | bearer | Never sends |
| `list_workspace_items()` | workspace | read | RO, I | bearer | |

Audit log columns: timestamp, user, tool, arguments (PII masked, letter bodies omitted), result,
trace id, ok. Table `audit_log` has UPDATE and DELETE revoked; file fallback is append-only JSONL.

## Third-party servers

| Server | Used for | Trust rationale |
|---|---|---|
| Upwork official MCP (`https://mcp.upwork.com/mcp`, OAuth 2.1) | live-mode reads and proposal/message **drafts** | Operated by the platform itself under its automation policy; every write is a draft the user confirms on Upwork, so a misbehaving tool cannot send anything. Mapped onto the marketplace port in `mcp_servers/marketplace/adapters/upwork_live.py`; not exercised without an account. |
| GitHub official MCP (remote, read-only repos toolset `https://api.githubcopilot.com/mcp/x/repos/readonly`) | the X3 Portfolio builder and repository ingestion: `search_repositories`, `get_repository_tree`, `get_file_contents`, `list_commits` | Operated by GitHub; the read-only toolset URL exposes no write tools at all, each user connects with their own fine-grained read-only token (stored encrypted), and repository content is treated as untrusted data. |

## Agent allowlists

| Agent | Tools |
|---|---|
| Scout | marketplace: search_jobs, get_job, marketplace_health |
| Job Analyst | none |
| Risk Assessor | marketplace: get_client_history, get_job |
| Fit Matcher | portfolio: search_evidence, get_case_study, list_skills |
| Pricing Strategist | marketplace: get_client_history, get_connects_balance, marketplace_health |
| Proposal Writer | portfolio: search_evidence, get_case_study |
| Verifier / Critic | portfolio: search_evidence, get_case_study |
| Compliance Guard | none |
| Client Liaison | marketplace: list_threads, list_messages, send_message (after approval), get_job; workspace: get_free_slots, create_interview_hold, create_email_draft |
| Submitter (post-approval step) | marketplace: create_proposal_draft, submit_proposal, get_connects_balance |
| Portfolio builder (X3) | github: search_repositories, get_repository_tree, get_file_contents, list_commits; portfolio: list_skills |

## Running the servers

```bash
make mcp                                   # all three over streamable HTTP (8101-8103), bearer auth
uv run python -m mcp_servers.portfolio.server   # stdio, for Claude Desktop / Cursor / MCP Inspector
npx @modelcontextprotocol/inspector uv run python -m mcp_servers.portfolio.server
```
