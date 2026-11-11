## rag

| Variant | Evidence Recall@5 | MRR | nDCG@10 | Unsupported claims / proposal | Judge score | GigSim reply rate | p95 retrieval latency (s) | Cost / proposal (USD) | Source |
|---|---|---|---|---|---|---|---|---|---|
| V0 naive dense | 0.655 | 0.409 | 0.469 | – | – | – | 0.84 | – | evals/results/rag_v0_naive.json |

## rag_personas

| Variant | ai_ml R@5 | fullstack R@5 | data_analyst R@5 | Source |
|---|---|---|---|---|
| V0 naive dense | 0.700 | 0.609 | – | evals/results/rag_summary.json |

## decisions

_Not yet run: `make eval-decisions`._

## multiagent

_Not yet run: `uv run python -m evals.runners.multiagent_compare`._

## tools

_Not yet run: `uv run python -m evals.runners.tool_design_eval`._

## safety

_Not yet run._
