---
version: 1
node: verifier
output: claims
---
## system
Split a proposal into atomic factual claims about the freelancer: experience, skills, past projects, clients, results, numbers, credentials, years. Ignore sentences that are plans, offers, questions or opinions about the client's project. For each claim give the exact sentence fragment and the evidence ids cited next to it (ids look like [abc123]). Return JSON: {{"claims": [{{"text": "...", "cited_evidence_ids": ["..."]}}]}}. At most 15 claims.

## user
Proposal:
{proposal}
