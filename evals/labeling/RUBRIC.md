# Scoring rubric for the judge calibration sheet

You score 30 proposals in `judge_sheet.csv`, each against the job post in the same row. Read the
job first, then the proposal, as if you were the client deciding whether to reply. Give each
criterion a whole number from 1 to 5 in its `human_*` column. Do not look at the judge's scores;
they are not in the sheet. Score each row on its own, without comparing rows. About 1–2 minutes
per row.

| Column | 1 (poor) | 3 (fair) | 5 (excellent) |
|---|---|---|---|
| `human_relevance` | Ignores what the client asked for | Covers the main deliverable, misses constraints | Addresses this client's deliverables, stack and constraints |
| `human_specificity` | Generic claims anyone could make | Some concrete detail | Concrete past work and results tied to this job |
| `human_credibility` | Hype, guarantees or claims that look invented | Plausible but unsupported | Every claim is plausible and backed; no hype or guarantees |
| `human_clarity` | Hard to read, far too long or too short | Readable, uneven structure | Easy to read, well structured, roughly 140 to 220 words |
| `human_next_step` | No next step | A vague offer to talk | A concrete first step or milestone plan |
| `human_overall` | Would not reply | Might reply | Would very likely reply |

Be strict: a template-like proposal ("I am a passionate...", "Dear Sir...") should not get more
than 3 overall. Use `notes` for anything unusual. Save the file under the same name when done.

The judge model uses the same criteria (`agent/prompts/judge.md`). We then report how often your
scores and the judge's agree (Cohen's kappa) in `evals/results/judge_calibration.json`.
