# GigSim: the marketplace simulator

`GIGSIM_ORIGIN=student-built`

GigSim is part of this project: the course asks each student to build their own simulator. It is
a safe, repeatable stand-in for a real freelance marketplace, and every outcome metric (reply and
hire rate) is measured here. The only code that talks to it is
`mcp_servers/marketplace/adapters/gigsim.py`, which maps the REST contract below onto the
marketplace port. `python scripts/ci_checks.py --freeze-gigsim` writes `gigsim/.lock.sha256`
when the simulator is final, after which CI fails on any change under this folder.

## What it simulates
- **Jobs**: 2,100 real Upwork posts (two public Kaggle datasets, see `docs/DATA_CARD.md`) across
  three persona categories, plus 153 planted posts: scams, prompt-injection text and duplicates.
  Jobs start in a hidden pool and are released as "new postings" via `POST /admin/tick`.
- **Clients** with public history (spend, rating, hires, verification) and **hidden
  preferences** (must-have skills, budget ceiling, dislike of generic openings, concision,
  whether screening answers matter). The hidden preferences are never served by the API.
- **Decisions**: when a proposal is submitted the client reacts and the proposal moves to
  `viewed | replied | interview | hired | lost`; replies create message threads.
  - `GIGSIM_CLIENT_MODE=rules` (default): a deterministic score from the hidden preferences.
  - `GIGSIM_CLIENT_MODE=llm`: an open model also reads the proposal as that client
    (`gigsim/client_llm.py`, prompt in `gigsim/prompts/client_decision.md`) and returns its
    interest, concerns and the reply it would write. Its interest is blended with the rule score
    (`GIGSIM_LLM_WEIGHT`, default 0.5), so must-have skills and the budget ceiling always count,
    and the client's own reply becomes the first message. The model is
    `GIGSIM_CLIENT_LLM=ollama:qwen3:4b-instruct` by default (free, local) or `groq:<model>`.
    Decisions run in a background worker, like a real client reading later: `POST /proposals`
    returns `status: submitted, decided: false`, and `GET /proposals/{id}` shows the reaction
    once `decided` is true. Pending decisions resume after a restart.
  - In both modes the dice are seeded on the job and the letter, and model judgements are cached
    (`GIGSIM_LLM_CACHE`), so the same proposal always gets the same reaction. Scam posters never
    reply. If the model is unavailable the client decides by rules and the breakdown records it.
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
