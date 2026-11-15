## rag

| Variant | Evidence Recall@5 | MRR | nDCG@10 | Unsupported claims / proposal | Judge score | GigSim reply rate | p95 retrieval latency (s) | Cost / proposal (USD) | Source |
|---|---|---|---|---|---|---|---|---|---|
| V0 naive dense | 0.672 | 0.432 | 0.486 | 0.000 | – | 0.333 | 2.08 | 0.0060 | evals/results/rag_v0_naive.json |
| V2 hybrid BM25 + dense (RRF) | 0.693 | 0.441 | 0.505 | 0.000 | – | 0.167 | 1.65 | 0.0060 | evals/results/rag_v2_hybrid.json |
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

| Metric | Value | Source |
|---|---|---|
| Bid-or-skip F1 | 0.621 | evals/results/decision_eval.json |
| Scam precision / recall | 0.667 / 0.167 | evals/results/decision_eval.json |
| Injection posts flagged | 0.444 | evals/results/decision_eval.json |
| Price inside the fair band | 1.000 | evals/results/decision_eval.json |
| p50 / p95 latency per job analysed (s) | 61.6 / 145.3 | evals/results/decision_eval.json |
| Mean cost per job analysed (USD) | 0.00200 | evals/results/decision_eval.json |
| Jobs evaluated | 60 | evals/results/decision_eval.json |

## multiagent

| System | Jobs | Failed runs | Bid-or-skip accuracy (completed runs) | Scam recall | Unsupported claims / proposal | Violations left in output | Violations caught | GigSim reply rate | Tokens / job | p95 latency (s) | Source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (a) single ReAct agent | 6 | 3 | 0.333 | – | – | 0 | 0 | – | 5454 | 42.9 | evals/results/multiagent_comparison.json |
| (b) langgraph-supervisor | 6 | 2 | 0.750 | – | – | 0 | 0 | – | 2740 | 9.4 | evals/results/multiagent_comparison.json |
| (c) GigBid graph | 6 | 0 | 0.833 | – | 0.000 | 0 | 0 | 0.000 | 15431 | 116.8 | evals/results/multiagent_comparison.json |

## tools

| Tool set | Selection accuracy | Argument accuracy | Tokens / task | Source |
|---|---|---|---|---|
| A. fine-grained (18 tools) | 0.950 | 0.825 | 2023 | evals/results/tool_design.json |
| B. coarse (3 tools) | 0.750 | 0.350 | 565 | evals/results/tool_design.json |
| C. fine-grained, rewritten descriptions | 0.975 | 0.875 | 2390 | evals/results/tool_design.json |

## safety

| Measure | Value | Source |
|---|---|---|
| Injection attack success without / with defences | 0.500 / 0.250 (n=4) | evals/results/injection.json |
| Proposals or messages sent without approval | 0 | evals/results/injection.json |
| X3 builder: unsupported claims before / after verification | 0.140 / 0.006 | evals/results/x3_eval.json |
| X3 builder: library recall from code | 0.402 | evals/results/x3_eval.json |
| X3 Recall@5 on repo projects: no case studies / builder / written | 0.722 / 0.730 / 0.743 | evals/results/x3_eval.json |
