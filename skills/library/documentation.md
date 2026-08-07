---
name: documentation
description: "Write docs that answer 'why', not 'what'. README, docstrings, ADRs. Update docs in the same PR as the code change."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [documentation, readme, docstrings, adr]
---

# Documentation

Use this skill when writing or updating documentation.

## Principles

1. **Docs answer WHY; code answers WHAT.** Don't paraphrase the code.
2. **Audience matters.** README is for newcomers; ADRs are for future maintainers; docstrings are for API users.
3. **Keep docs with code.** Update docs in the same commit as the code change.
4. **Examples > explanations.** A working example teaches more than 3 paragraphs.
5. **Date your docs.** Stale docs are worse than no docs.

## README structure

```markdown
# Project Name

<one-sentence description>

## Quick Start
<3-5 commands to get a "hello world" running>

## Why?
<2-3 sentences on the problem this solves>

## Installation
<detailed setup>

## Usage
<common workflows with examples>

## Configuration
<all options, with defaults>

## Architecture
<link to ARCHITECTURE.md, or inline diagram>

## Contributing
<link to CONTRIBUTING.md>

## License
```

## Docstring style (Python — Google style)

```python
def search(query: str, limit: int = 10) -> list[Result]:
    """Search the index for matching documents.

    Args:
        query: Search query, supports boolean operators (AND, OR, NOT).
        limit: Maximum number of results to return. Default 10.

    Returns:
        List of Result objects, ranked by relevance.

    Raises:
        ValueError: If query is empty or malformed.
        SearchError: If the index is corrupted.

    Example:
        >>> search("python AND async", limit=5)
        [Result(title="asyncio docs", score=0.95), ...]
    """
```

## Architecture Decision Records (ADR)

`docs/adr/NNNN-title.md`:
```markdown
# ADR-NNNN: Title

Date: YYYY-MM-DD
Status: Proposed | Accepted | Deprecated | Superseded by ADR-XXXX

## Context
<the problem, forces, constraints>

## Decision
<what we decided>

## Consequences
<positive, negative, neutral>

## Alternatives Considered
<option B> — rejected because <reason>
<option C> — rejected because <reason>
```

## Anti-patterns

- ❌ README that's just "TODO"
- ❌ Docstring that says "returns the result" — the function signature already says that
- ❌ Outdated examples that don't run
- ❌ Documentation in a separate repo from the code
- ❌ No date on architectural docs
- ❌ Tutorials that assume knowledge the target audience doesn't have
