# GigSim (student-built stand-in)

`GIGSIM_ORIGIN=student-built`

The instructor-provided GigSim simulator was not included in the starter kit received. This
folder contains a functionally equivalent simulator so the whole system could be built and
measured. When the official GigSim arrives it replaces this folder; the only code that talks to
it is `mcp_servers/marketplace/adapters/gigsim.py`, which maps the REST contract below onto the
marketplace port. After the swap, `gigsim/.lock.sha256` freezes the folder and CI fails on any
change under it.

## What it simulates
- **Jobs**: 2,100 real Upwork posts (two public Kaggle datasets, see `docs/DATA_CARD.md`) across
  three persona categories, plus 153 planted posts: scams, prompt-injection text and duplicates.
  Jobs start in a hidden pool and are released as "new postings" via `POST /admin/tick`.
- **Clients** with public history (spend, rating, hires, verification) and **hidden
  preferences** (must-have skills, budget ceiling, dislike of generic openings, concision,
  whether screening answers matter). The hidden preferences are never served by the API.
- **Decisions**: when a proposal is submitted the client scores it and the proposal moves to
  `viewed | replied | interview | hired | lost`; replies create message threads. Default mode is
  deterministic (`GIGSIM_CLIENT_MODE=rules`) so evaluations are reproducible; `llm` lets a small
  open model play the client with the rule score as fallback.
- **Connects**: each proposal spends the job's Connects cost; `402` when the balance is too low.
- **Rate limits** (`60/min` per token, `429` with `Retry-After`) and **chaos** (`GIGSIM_CHAOS_RATE`,
  default 2 % of requests return `503`).
- **Idempotency**: every write carries an `idempotency_key`; a retried call returns the stored
  response instead of acting twice. `dry_run: true` returns exactly what would be sent.

## REST contract
| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/policy` | no auth; `/policy` exposes `version` and Connects rules |
| GET | `/jobs?q=&skills=&payment_type=&min_budget=&posted_after=&page=&limit=` | open jobs |
| GET | `/jobs/{id}` | includes client summary |
| GET | `/clients/{id}` | public history and past jobs |
| GET | `/me`, `/me/connects` | account and balance |
| POST | `/proposals` | `{job_id, cover_letter, bid_amount, bid_type, screening_answers, idempotency_key, dry_run}` |
| GET | `/proposals`, `/proposals/{id}` | |
| GET | `/threads`, `/messages?thread_id=` | |
| POST | `/messages` | `{thread_id, body, idempotency_key, dry_run}` |
| GET | `/events?since_id=` | pipeline events |
| POST | `/admin/tick?n=&persona=`, `/admin/reset`, `/admin/connects` | dev only |

Auth: `Authorization: Bearer <api_key>`; accounts from `GIGSIM_ACCOUNTS="key:freelancer_id:Name,..."`.

## Run
```bash
uv run uvicorn gigsim.app:app --port 8081        # or: make gigsim
```
Seed files live in `gigsim/seed/` and are produced by `data/scripts/prepare_jobs.py` and
`data/scripts/inject_adversarial.py`.
