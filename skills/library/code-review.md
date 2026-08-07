---
name: code-review
description: "Structured code review: correctness, security, performance, maintainability. Use PR template; never merge without explicit LGTM."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [review, quality, pull-request]
  related_skills: [test-driven-development, systematic-debugging]
---

# Code Review

Use this skill when reviewing a pull request or diff.

## Checklist

### Correctness
- [ ] Tests cover the new behavior
- [ ] Tests cover the edge cases (empty, null, large, negative)
- [ ] Error paths are tested
- [ ] No obvious logic bugs
- [ ] Race conditions / concurrency considered

### Security
- [ ] No hardcoded secrets, tokens, passwords
- [ ] User input validated and sanitized
- [ ] SQL/NoSQL queries parameterized
- [ ] File paths checked for traversal (`..`)
- [ ] Commands shell-escaped or use safe APIs
- [ ] Auth checks present on new endpoints
- [ ] Rate limiting on expensive operations

### Performance
- [ ] No N+1 queries in loops
- [ ] No accidental O(n²) on large inputs
- [ ] Caches invalidated appropriately
- [ ] No blocking I/O on hot paths
- [ ] Memory: no unbounded growth / leaks

### Maintainability
- [ ] Names are clear (no `n`, `x`, `temp`, `data2`)
- [ ] Functions do one thing
- [ ] Comments explain WHY, not WHAT
- [ ] No commented-out code
- [ ] No dead code
- [ ] Public API documented
- [ ] Types / docstrings on public functions

### Style
- [ ] Matches existing project style
- [ ] Linter passes
- [ ] Formatter applied
- [ ] No trailing whitespace / EOL issues

## Output Format

```
## Summary
<1-2 sentences: what this PR does>

## Blockers (must fix before merge)
- [file:line] issue description

## Suggestions (consider but not required)
- [file:line] suggestion

## Nits (optional)
- typo, style, etc.

## LGTM?
<yes / no / yes-with-nits>
```

## Anti-patterns

- ❌ "Looks good to me" without reading the code
- ❌ Bikeshedding style when there are correctness bugs
- ❌ Asking for changes without explaining why
- ❌ Reviewing your own code without a second pair of eyes
- ❌ Approving because the author is senior / pressured for time
