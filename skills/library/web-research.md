---
name: web-research
description: "Multi-source web research: search → fetch → verify → synthesize → cite. Always cross-reference claims from 2+ sources."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [research, web, fact-checking, synthesis]
---

# Web Research

Use this skill when the user asks a factual question that requires
current information or that you cannot answer from training data alone.

## Workflow

### 1. Decompose the question
Break the question into sub-questions. "What's the best Python web framework?"
becomes:
- What Python web frameworks exist?
- What are their features?
- What are their performance characteristics?
- What are their community sizes?
- What use cases is each best for?

### 2. Search broadly
- Use `web_search` with multiple query formulations
- Don't trust the first result — search at least 2-3 different ways
- Note the sources you find (URL, title, date)

### 3. Fetch deeply
- `web_fetch` the most promising 2-4 sources
- Skim for the key claims
- Note direct quotes for citation

### 4. Verify
- Cross-reference important claims across 2+ independent sources
- Flag claims that appear in only one source
- Distinguish: primary source (paper, official docs) vs secondary (blog, news)

### 5. Synthesize
- Lead with the direct answer (BLUF — bottom line up front)
- Then context / caveats
- Then the supporting detail
- Cite inline as [1], [2], with full sources at the end

## Citation Format

```
According to [1], FastAPI is the fastest Python framework for async APIs,
with benchmarks showing 2-3x throughput over Flask [2]. However, Flask
remains more widely deployed [3] and has a larger extension ecosystem [1].

## Sources
[1] FastAPI docs — https://fastapi.tiangolo.com/benchmarks/ (2026)
[2] TechEmpower Framework Benchmarks — https://www.techempower.com/benchmarks/ (2026-08)
[3] Python Developers Survey 2025 — https://survey.python.org/ (2025-12)
```

## Anti-patterns

- ❌ Citing only the first search result
- ❌ Mixing primary and secondary sources without distinction
- ❌ Confident assertions about future events
- ❌ "According to sources" without naming them
- ❌ Trusting AI-generated content as a source

## Tools

- `web_search` — find sources
- `web_fetch` — read full pages
- `web_scrape` — extract structured data (tables, lists)
- `execute_code` — analyze scraped data
