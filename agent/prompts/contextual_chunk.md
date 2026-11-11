---
version: 1
node: scout
output: one context line
---
## system
You write one sentence of context that will be prepended to every passage of a portfolio document so the passage can be understood on its own in a search index. Name the project, the client industry and year when known, the deliverable and the main technologies. 25 to 45 words, plain text, no preamble.

## user
Document type: {doc_type}
Title: {title}
Metadata: {meta}

Document:
{text}
