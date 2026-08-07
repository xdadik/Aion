---
name: systematic-debugging
description: "Reproduce → Isolate → Hypothesize → Test → Fix → Verify. Never guess-and-check; always form a hypothesis before changing code."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [debugging, troubleshooting, root-cause]
  related_skills: [test-driven-development, code-review]
---

# Systematic Debugging

Use this skill whenever something is broken and the cause isn't obvious.

## The Method

### 1. Reproduce
- Make it fail on demand. If you can't reproduce, you can't fix.
- Note the EXACT steps, inputs, environment.
- Minimize the repro: smallest input, fewest steps.

### 2. Isolate
- Binary search: comment out half, does it still fail?
- Bisect commits: `git bisect start` → mark good/bad until you find the regression.
- Swap components: does it fail with mock data? With a different library version?

### 3. Hypothesize
- Form a specific, falsifiable hypothesis: "The bug is in `parse()` because `line.split(',')` doesn't handle quoted commas."
- Write down the hypothesis. Don't skip this step.
- Identify the test that would prove it wrong.

### 4. Test
- Run the test. Don't change code yet.
- If hypothesis confirmed → proceed to Fix.
- If hypothesis falsified → return to Isolate with new info.

### 5. Fix
- Write a test that reproduces the bug (RED).
- Implement the fix (GREEN).
- Run the FULL test suite, not just the new test.

### 6. Verify
- Run the original failing scenario manually.
- Check for regressions in related code paths.
- Document the root cause in the commit message.

## Anti-patterns

- ❌ "Let me try changing this and see if it works" — guessing
- ❌ Changing multiple things at once
- ❌ Fixing the symptom, not the cause
- ❌ Skipping the regression test
- ❌ "Works on my machine" — environment matters

## Tools

- `execute_code` — print statements, assertions
- `run_shell` — `git bisect`, `git blame`, `grep -rn`
- `read_file` — read the failing code path
- `web_search` — known issues with libraries
