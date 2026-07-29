# Contributing to Aion Hand

First off — thank you for taking the time to contribute. 🙏

Aion Hand is built in the open by a small team and we welcome
contributions of every size: bug reports, doc fixes, new tools, new
verifiers, performance work, or entirely new subsystems. This document
explains how to do all of that without friction.

> **TL;DR** — fork the repo, branch off `main`, run `make dev`, code
> with `ruff` + `black`, write a test, open a PR with a clear
> description. That's 90% of it.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Development Workflow](#2-development-workflow)
3. [Code Style](#3-code-style)
4. [Commit Messages](#4-commit-messages)
5. [Pull Request Template](#5-pull-request-template)
6. [Issue Templates](#6-issue-templates)
7. [Testing Requirements](#7-testing-requirements)
8. [Review Process](#8-review-process)
9. [Security Contributions](#9-security-contributions)

---

## 1. Getting Started

### Prerequisites

- **Python 3.11+** (we test on 3.11, 3.12, 3.13)
- **Git 2.30+**
- **make** (optional but convenient)
- An LLM provider API key for live testing (OpenAI, Anthropic, OpenRouter,
  or local Ollama). Not required for unit tests.

### Fork and clone

```bash
# 1. Fork via the GitHub UI, then:
git clone https://github.com/<your-username>/aion-hand.git
cd aion-hand

# 2. Add the upstream remote
git remote add upstream https://github.com/aion-hand/aion-hand.git
git fetch upstream

# 3. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 4. Install in editable mode with all dev dependencies
make dev
# equivalent to: pip install -e ".[all,dev]"
```

### Verify your setup

```bash
make test          # should pass all tests
make lint          # should report no issues
python -m aion_hand_cli --version
```

If any of those fail, please open an issue with the full output — it's
likely an environment problem worth fixing for everyone.

---

## 2. Development Workflow

### Branch strategy

```text
main              ← always green, always releasable
└── feature/foo   ← your work lives here
└── fix/bar       ← bug fixes
└── docs/baz      ← documentation only
```

- Branch from `main`: `git checkout -b feature/my-feature upstream/main`.
- Rebase onto `main` before opening a PR if `main` has moved.
- Keep branches short-lived (days, not weeks).
- One logical change per branch — if you find yourself writing "and also
  …" in the PR description, consider splitting it.

### The loop

1. **Plan** — open an issue or comment on an existing one saying you're
   working on it. This avoids duplicated effort.
2. **Code** — write the change, following the [Code Style](#3-code-style)
   below.
3. **Test** — add or update tests. See [Testing Requirements](#7-testing-requirements).
4. **Lint** — `make lint && make format`.
5. **Commit** — small, well-described commits following
   [Commit Messages](#4-commit-messages).
6. **Push** — push to your fork.
7. **PR** — open a pull request against `main` using the
   [PR template](#5-pull-request-template).
8. **Review** — respond to review comments, push fixes, re-request
   review when ready.
9. **Merge** — a maintainer merges once CI is green and at least one
   reviewer has approved.

### Keeping your fork up to date

```bash
git fetch upstream
git checkout main
git rebase upstream/main
git push origin main --force-with-lease
```

---

## 3. Code Style

We use **`ruff`** for linting and **`black`** for formatting. Both are
already configured in `pyproject.toml`.

### Format and lint

```bash
make format    # runs black + ruff --fix
make lint      # runs ruff check (non-fixing)
```

### Style rules

- **Line length:** 88 characters ( enforced by `black` and `ruff`).
- **Target Python:** 3.11 — do not use 3.12-only syntax.
- **Imports:** sorted by `ruff` (`isort` rules). Use `from __future__
  import annotations` at the top of every module so type hints can
  reference forward declarations.
- **Typing:** all public functions and classes must have type
  annotations. Run `mypy aion_core/` to verify.
- **Docstrings:** every public class and function gets a docstring.
  Module-level docstrings explain what the module does and which
  classes it exposes.
- **Async-first:** all I/O-bound code must be `async`. Sync wrappers
  are acceptable only at the CLI boundary.
- **No `print()` in library code** — use the `logging` module. `print`
  is reserved for the CLI.
- **No bare `except:`** — catch `Exception` at minimum, ideally the
  specific exception type.
- **Tests live in `tests/`** and mirror the source layout
  (`aion_core/security/sandbox.py` → `tests/test_security.py`).

### Type checking

```bash
mypy aion_core/ aion_hand_cli/     # strict
```

If `mypy` complains about third-party code, add `# type: ignore[<code>]`
with a comment explaining why. Blind `# type: ignore` is a code smell.

---

## 4. Commit Messages

We follow a lightweight version of [Conventional Commits](https://www.conventionalcommits.org/).

### Format

```text
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

| Type       | When to use                                                |
|------------|------------------------------------------------------------|
| `feat`     | A new feature                                              |
| `fix`      | A bug fix                                                  |
| `docs`     | Documentation only                                         |
| `style`    | Formatting, whitespace, no code change                     |
| `refactor` | Code restructuring with no behaviour change                |
| `perf`     | Performance improvement                                    |
| `test`     | Adding or fixing tests                                     |
| `chore`    | Build, CI, tooling, dependencies                           |
| `security` | Security fix — also see [Security Contributions](#9-security-contributions) |

### Scope

Optional. Use the module name: `security`, `memory`, `tools`, `mcp`,
`pipeline`, `orchestration`, `cli`, `docs`.

### Examples

```text
feat(mcp): add SSE transport reconnection with backoff

Adds exponential backoff to the SSE transport's reconnect logic so
that flaky MCP servers don't cause permanent client teardown.

Closes #142.
```

```text
fix(security): block `pathlib` in sandbox runner

`pathlib.Path` could be used to traverse the filesystem without
`open()`, bypassing the restricted builtins. Added `pathlib` to the
deny-list.
```

```text
docs: clarify sandbox limitations in SECURITY.md
```

### Rules

- Subject line ≤ 72 characters, imperative mood ("add", not "added").
- Body wrapped at 80 chars, explains **why** not **what**.
- Reference issues with `Closes #N`, `Fixes #N`, or `Refs #N`.
- Sign your commits (`git commit -s`) if you want them attributable.
  We don't require DCO, but we appreciate it.

---

## 5. Pull Request Template

Copy this into your PR description. The GitHub repo has it saved as a
`.github/pull_request_template.md` so it auto-populates.

```markdown
## What does this PR do?

<!-- One-paragraph summary, plus a bullet list of changes -->

## Why is this change needed?

<!-- Link to issue, or explain the problem -->

## How was it tested?

- [ ] Unit tests added / updated
- [ ] `make test` passes locally
- [ ] `make lint` passes locally
- [ ] Manually tested (describe below)

## Checklist

- [ ] Code follows the style guide (`make format` is clean)
- [ ] Public API changes are documented
- [ ] Changelog updated (if applicable)
- [ ] No new dependencies without justification
- [ ] No secrets, API keys, or tokens in the diff

## Breaking changes

<!-- If yes, describe migration path. If no, write "None". -->

## Screenshots / logs

<!-- For CLI / UI changes only -->
```

---

## 6. Issue Templates

### Bug report

```markdown
**Describe the bug**
A clear description of what the bug is.

**To reproduce**
Steps that trigger the bug:
1. Run `aion-hand chat`
2. Type `...`
3. See error

**Expected behaviour**
What you expected to happen.

**Actual behaviour**
What actually happened, including stack traces and logs.

**Environment**
- Aion Hand version: [e.g. 0.1.0]
- Python version: [e.g. 3.12.1]
- OS: [e.g. macOS 14.2]
- Provider: [e.g. OpenAI gpt-4o]
- Were you running in Docker / firejail / bare metal?

**Configuration**
Redact API keys. Paste your `~/.aion-hand/config.json` if relevant.
```

### Feature request

```markdown
**Is your feature request related to a problem?**
A description of the problem.

**Proposed solution**
A clear description of what you want to happen.

**Alternatives considered**
Other solutions you've considered.

**Additional context**
Anything else. Screenshots, links, prior art.
```

### Security report

**Do not file a public issue for security vulnerabilities.** See
[`SECURITY.md`](SECURITY.md#5-reporting-vulnerabilities) for the
private disclosure process.

---

## 7. Testing Requirements

### Layout

```
tests/
├── __init__.py
├── test_core.py              # agent.core, agent.loop
├── test_memory.py            # memory.manager
├── test_tools.py             # tools.registry
├── test_security.py          # security.sandbox
├── test_orchestration.py     # orchestration.engine
├── test_cron.py              # cron.scheduler
├── test_skills.py            # skills.engine
└── test_providers.py         # providers.factory
```

### Running tests

```bash
make test                  # full suite, verbose
pytest tests/ -k security  # only tests matching "security"
pytest --cov=aion_core     # with coverage report
```

### What we require in a PR

- **Bug fix:** a regression test that fails before your fix and passes
  after.
- **New feature:** tests covering the happy path and at least one edge
  case.
- **Security change:** tests for every new blacklist/whitelist pattern,
  every new module block, every new verifier rule. See
  `tests/test_security.py` for the existing pattern.
- **Refactor:** existing tests still pass. If they don't, the refactor
  is changing behaviour and should be split into a fix + a refactor.

### Coverage

We don't enforce a hard coverage threshold, but we aim for ≥80% on
`aion_core/`. Run `pytest --cov=aion_core --cov-report=html` and open
`htmlcov/index.html` to see what's missing.

### Async tests

We use `pytest-asyncio` in auto mode. Mark async tests with `async def`
and they'll be run automatically — no `@pytest.mark.asyncio` needed.

### Live integration tests

Tests that hit a real LLM API are tagged `@pytest.mark.live` and skipped
by default. Run them with `pytest --run-live` after setting
`OPENAI_API_KEY` (or your provider's equivalent). These are not required
for PR approval but are appreciated for provider-related changes.

---

## 8. Review Process

### Who reviews

- **Small PRs** (docs, typo, single-file fix): one maintainer review.
- **Medium PRs** (new tool, new verifier, refactors): two maintainer
  reviews, one from a subsystem owner.
- **Large PRs** (new subsystem, breaking changes): two maintainer
  reviews plus a 72-hour waiting period for community comment.

### What reviewers look for

1. **Correctness** — does it do what the PR says?
2. **Tests** — are they meaningful, not just coverage padding?
3. **Security** — does it weaken any boundary? If yes, is it justified
   and documented?
4. **API stability** — does it break existing public APIs? If yes, is
   the breakage worth it and is migration documented?
5. **Performance** — does it add O(n²) loops in hot paths?
6. **Docs** — are docstrings and user-facing docs updated?
7. **Style** — does `make lint` pass?

### Response times

- First response from a maintainer: **within 3 business days**.
- Review turnaround after you push fixes: **within 2 business days**.
- If a PR has been silent for >7 days, ping us in `#development` on
  Discord or comment `@aion-hand/maintainers` on the PR.

### Disagreements

We discuss, we don't argue. If you disagree with a review comment:
explain your reasoning once, clearly. If we still disagree, we'll
explain why. If we can't agree, the final call rests with the subsystem
owner — but we will always explain the reasoning in the PR thread.

---

## 9. Security Contributions

Security-related contributions are held to a higher bar:

- **Sandbox changes** (anything in `aion_core/security/`) require two
  maintainer reviews, one of which must be from a security-focused
  maintainer.
- **New blacklist/whitelist patterns** must come with a regression test
  demonstrating the pattern blocks a real exploit payload.
- **New verifiers** must include both a passing and failing test case.
- **Changes to `SECURITY.md`** are treated like code: they need a PR,
  review, and the same commit-message conventions.

If you're contributing a security fix that you'd rather not discuss
publicly, see [Reporting Vulnerabilities](SECURITY.md#5-reporting-vulnerabilities)
in `SECURITY.md`.

---

## License

By contributing to Aion Hand, you agree that your contributions will be
licensed under the [MIT License](LICENSE). You retain copyright to your
own contributions; we just need the right to distribute them under the
project's license.

---

## Questions?

- 💬 **Discord:** [Aion Hand community](https://discord.gg/aion-hand)
- 📧 **Email:** contributors@aion-hand.dev
- 🐛 **Issues:** [github.com/aion-hand/aion-hand/issues](https://github.com/aion-hand/aion-hand/issues)

Thanks again for being here. Every contribution makes Aion Hand better
for everyone who runs it.
