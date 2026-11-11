# GigBid web app

Next.js 16 (App Router, TypeScript, Tailwind) front end for GigBid. It is the place where the
human stays in control: every proposal and client message is reviewed here before it leaves.

## Screens

| Route | What it does |
|---|---|
| `/login` | Sign in or create an account |
| `/onboarding` | Choose a demo persona or own profile, connect GigSim or Upwork (OAuth), upload portfolio, set rates, filters and weekly Connects budget |
| `/inbox` | New jobs ranked by fit with risk badges, recommended action, price and Connects cost; scout, analyse, skip |
| `/jobs/[id]` | JobSpec, risk report, requirement-to-evidence matrix, price rationale, bid-or-skip reasoning, live agent progress |
| `/studio/[id]` | Proposal studio: evidence on hover for every claim, Critic and Compliance comments, claim verification, regenerate one paragraph, approve / edit / reject, dry-run preview of what will be sent and its cost |
| `/pipeline` | Kanban from drafted to hired or lost, synced from marketplace events |
| `/messages` | Client threads with suggested replies and interview slots, approved before sending |
| `/runs`, `/runs/[id]` | Live node-by-node progress over SSE, execution trace, checkpoints with replay, link to the full trace |
| `/analytics` | Reply and hire rate by category, Connects versus outcomes, cost and latency against budget, rejection reasons, retrieval results |
| `/settings` | Autonomy, budgets, saved searches, connected accounts, memory viewer with delete |

## How it talks to the API

The browser only calls `/api/*` on its own origin; `next.config.ts` rewrites that to FastAPI
(`API_URL`, default `http://localhost:8000`) so the session cookie stays first-party and SSE
streams pass through. Types come from the API: `src/lib/api/schema.d.ts` is generated from
`openapi.json` and must not be edited by hand.

```bash
make openapi-client      # from the repo root: export the FastAPI schema and regenerate the client
npm run dev              # http://localhost:3000 (needs the API on :8000)
npm run lint && npm run typecheck
npm run test:e2e         # Playwright; the API is mocked at the network layer
```

## Tests

`tests/e2e/` covers onboarding, approving a proposal (including the evidence tooltip), rejecting
with a reason, editing a draft that is re-checked before approval, the degraded-mode banner,
the sign-in redirect, keyboard access and the mobile layout.
