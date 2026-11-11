## rag

| Variant | Evidence Recall@5 | MRR | nDCG@10 | Unsupported claims / proposal | Judge score | GigSim reply rate | p95 retrieval latency (s) | Cost / proposal (USD) | Source |
|---|---|---|---|---|---|---|---|---|---|
| V0 naive dense | 0.672 | 0.432 | 0.486 | – | – | – | 2.08 | – | evals/results/rag_v0_naive.json |
| V2 hybrid BM25 + dense (RRF) | 0.693 | 0.441 | 0.505 | – | – | – | 1.65 | – | evals/results/rag_v2_hybrid.json |
| V3 cross-encoder rerank | 0.654 | 0.420 | 0.479 | – | – | – | 77.45 | – | evals/results/rag_v3_rerank.json |
| V4 outcome-aware | 0.654 | 0.439 | 0.503 | – | – | – | 53.01 | – | evals/results/rag_v4_outcome.json |
| V5 multi-vector projects | 0.587 | 0.396 | 0.494 | – | – | – | 1.73 | – | evals/results/rag_v5_multivector.json |
| V8 corrective loop | 0.638 | 0.419 | 0.472 | – | – | – | 31.68 | – | evals/results/rag_v8_corrective.json |

## rag_personas

| Variant | ai_ml R@5 | fullstack R@5 | data_analyst R@5 | Source |
|---|---|---|---|---|
| V0 naive dense | 0.700 | 0.609 | 0.707 | evals/results/rag_summary.json |
| V2 hybrid BM25 + dense (RRF) | 0.731 | 0.586 | 0.760 | evals/results/rag_summary.json |
| V3 cross-encoder rerank | 0.754 | 0.500 | 0.707 | evals/results/rag_summary.json |
| V4 outcome-aware | 0.715 | 0.523 | 0.723 | evals/results/rag_summary.json |
| V5 multi-vector projects | 0.654 | 0.531 | 0.576 | evals/results/rag_summary.json |
| V8 corrective loop | 0.739 | 0.469 | 0.707 | evals/results/rag_summary.json |

## decisions

_Not yet run: `make eval-decisions`._

## multiagent

_Not yet run: `uv run python -m evals.runners.multiagent_compare`._

## tools

_Not yet run: `uv run python -m evals.runners.tool_design_eval`._

## safety

_Not yet run._
