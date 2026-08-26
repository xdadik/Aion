---
name: test-driven-development
description: "Red-Green-Refactor: write a failing test, implement minimal code to pass, then refactor. Never write production code without a failing test first."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [testing, tdd, development, quality]
  related_skills: [plan, systematic-debugging, code-review]
---

# Test-Driven Development

Use this skill whenever writing or modifying code.

## The Cycle

```
RED       Write a test that fails (describes the desired behavior)
  ↓
GREEN     Write the minimum code to make the test pass
  ↓
REFACTOR  Improve structure without changing behavior
  ↓
COMMIT    Small, atomic commit
  ↓
REPEAT
```

## Rules

1. **Write the test first.** Always. No exceptions for "trivial" code.
2. **One test at a time.** Don't write 5 tests then implement. One red, one green.
3. **Minimum code.** The GREEN step is the dumbest code that passes. Don't anticipate future tests.
4. **Refactor only when GREEN.** Never refactor with red tests.
5. **Commit after each cycle.** Small commits are bisectable.

## Test Quality

A good test:
- Has a descriptive name: `test_user_cannot_login_with_expired_token`
- Tests ONE behavior
- Follows AAA: Arrange, Act, Assert
- Doesn't depend on test order
- Fails informatively when broken

## When TDD feels slow

TDD feels slow for:
- Throwaway prototypes → don't TDD these
- Exploratory code → write the test after you understand the shape
- Bug fixes → **always** write the failing test first that reproduces the bug

## Anti-patterns

- ❌ Writing tests after the implementation
- ❌ Writing tests that pass without the implementation (tautological)
- ❌ Testing implementation details (private methods, internal state)
- ❌ Mocking what you don't own
- ❌ Skipping the refactor step
