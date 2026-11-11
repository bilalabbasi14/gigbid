# Signature extension: X3 Portfolio builder

**Turn a GitHub account into case studies automatically, verified against the code, and feed them
to the Portfolio server.**

## Why this extension

GigBid's central promise is that a proposal never claims experience the portfolio cannot back up.
That promise is only as good as the portfolio. Many freelancers, especially engineers, have far
more evidence in their repositories than in written case studies, so the Fit Matcher finds little
to cite and the Writer has to stay vague. The builder closes that gap without weakening the
promise: it writes case studies only from facts it can point to in the code.

## How it works

```text
list_repos ──▶ draft_repo (one parallel branch per repository) ──▶ review (interrupt) ──▶ save
```

| Step | What happens | Code |
|---|---|---|
| Read | Repositories are listed and read through the **official GitHub MCP server** (remote endpoint restricted to the read-only repos toolset, `https://api.githubcopilot.com/mcp/x/repos/readonly`) with the user's own token. A local source reads the demo personas' repositories so the feature also works offline. | `agent/portfolio_builder/sources.py` |
| Extract facts | Deterministic facts with stable ids: languages from the file tree, dependencies from manifests mapped to frameworks, imports in sampled source files, tests, CI, containers, notebooks, commit history, and README paragraphs marked as the author's own statements. | `agent/portfolio_builder/facts.py` |
| Draft | The model writes a short case study and must cite a fact id for every claim; metrics or client claims that only the README supports must be attributed to the README; nothing about clients, users or revenue may be invented. | `agent/prompts/portfolio_builder.md` |
| Verify | The same claim verifier the proposal pipeline uses splits the draft into claims and checks each against the facts (cross-encoder support plus a model judgement); unsupported sentences are removed or rewritten. | `rag/verify.py` |
| Review | The graph pauses with `interrupt()`; the Portfolio page shows each draft with every claim's code fact on hover, the verification numbers, and approve, edit or reject per case study. | `apps/web/src/app/portfolio/page.tsx` |
| Save | Approved case studies are written into the user's own portfolio marked `verified: true` with their facts (`FACTS.json`) and indexed incrementally, so the Fit Matcher and Writer can cite them in the next proposal. | `agent/graphs/portfolio_builder_graph.py` |

Safety: the GitHub endpoint is read-only by construction, repository text is treated as untrusted
data (delimited and neutralised before any prompt), and nothing enters the portfolio without the
person approving it.

## How it is measured

`evals/runners/x3_eval.py`, results in `evals/results/x3_eval.json`.

1. **Does it recover what written case studies give retrieval?** For each persona, three indexes
   are compared on the dev jobs whose gold projects are repository projects: the original corpus
   (written case studies for every project), a *base* corpus with the case studies of repository
   projects removed (a freelancer with code on GitHub but no write-ups), and *built*: base plus the
   builder's case studies. Metric: evidence Recall@5, MRR and nDCG@10 with the shipped retriever.
2. **Is what it writes true?** Claim labels before repair and the unsupported-claim rate after,
   facts cited per case study, and **library recall and precision** against each project's own
   metadata (did reading the code find the stack the project actually used?).

Results are reported in the README's safety table and in the R&D report, including where the
builder falls short (for example repositories whose README is the only description, which yields
few verifiable facts and is skipped).
