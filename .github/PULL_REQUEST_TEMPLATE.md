## Pull request checklist

- [ ] **Tests added** — bug fixes and new features MUST include tests
- [ ] **All tests pass** — `pytest --tb=short -q` exits 0
- [ ] **Lint clean** — `ruff check aion_core/ tests/` reports no errors (warnings OK)
- [ ] **Docs updated** — README.md / CHANGELOG.md / ARCHITECTURE.md updated if user-facing
- [ ] **No secrets** — no API keys, tokens, passwords, or PII in the diff
- [ ] **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/):
      `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`

## Description

What does this PR do? Why is it needed?

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (would cause existing functionality to not work)
- [ ] Documentation update
- [ ] Refactor / cleanup
- [ ] Test addition / improvement

## How has this been tested?

Describe the tests you ran. Include repro steps if applicable.

```
# Paste test output or repro commands here
```

## Related issues

Closes #XXX
Refs #YYY

## Screenshots / logs (if applicable)

Drag screenshots here. Paste logs in ```text blocks.

## Checklist for reviewers

- [ ] Tests adequately cover the change
- [ ] Code follows existing style (no reformatting of unrelated lines)
- [ ] No commented-out code
- [ ] No `print()` debugging left in
- [ ] Public API changes are documented
- [ ] CHANGELOG.md updated (if user-facing)
