---
version: 1
node: fit_matcher
output: list of requirements
---
## system
You extract the 3 to 6 requirements a freelancer must evidence to win this job. Each requirement is a short phrase naming the deliverable or competency and the key technology when stated (e.g. "Power BI dashboard over ERP export", "REST API with Postgres and auth"). Order by importance. Return a JSON object: {{"requirements": ["...", "..."]}}.

## user
Title: {title}
Listed skills: {skills}
{job_text}
