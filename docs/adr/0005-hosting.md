# ADR 0005: Hosting the public URL

**Status:** accepted · **Date:** 2026-11-13 · **Supersedes:** the Hugging Face Space plan of
milestone 8

## Context
The brief requires a public URL that stays live until grades are released, with a reviewer login,
and the hidden test runs new GigSim jobs and clients against it. GigBid is more than a web app:
the API runs graphs that take minutes, a worker scouts on a schedule, the MCP servers and GigSim
run beside it, and the CPU embedding and reranking models need roughly 1.3 GB per process. We
estimate the whole stack peaks around 3.5 GB of memory (to be measured on the VM). The hosting
budget is zero.

Options checked in November 2026:

| Option | Why not, or why |
|---|---|
| Hugging Face Docker Space (the original plan) | Docker and Gradio Spaces now need a paid PRO plan; only static Spaces are free |
| Vercel Hobby | Right for the Next.js app, wrong for the backend: functions get 2 GB and 5 minutes per request, scale to zero after 5 idle minutes (every cold start reloads the models), and containers and background daemons are in beta |
| Render free | Sleeps after 15 idle minutes with about a minute to wake; background workers are not free |
| Oracle Cloud Always Free | Ample resources, but sign-up needs a card for identity checks |
| **Azure for Students** | $100 credit with no card for full-time students; a B2s VM (2 vCPU, 4 GiB) costs roughly $30 a month (estimate), so the credit covers about three months |

## Decision
Run the existing single-container image on one Azure for Students VM, behind Caddy for HTTPS,
with Postgres on Neon's free plan (`infra/vm/`, runbook section 3). GitHub Actions deploys over
SSH on every push to main and checks the URL every 6 hours. The simulated clients use a small
hosted model there, because the VM has no room for a local one.

## Consequences
- One always-on machine: no cold starts and no request time limit for long graph runs.
- 4 GiB is tight; a 4 GB swap file absorbs image builds and peaks. If memory runs short, the
  worker can be turned off (`RUN_WORKER=0`): analyses still run inside the API, but scheduled
  scouting and pipeline sync stop, so the reviewer scouts by hand. The VM can also be resized at
  about twice the cost.
- The credit has to outlast grading; a $20-a-month budget alert guards it.
- Moving hosts later is cheap: the same image runs anywhere Docker runs.
