---
name: git-workflow
description: "Conventional commits, feature branches, PR flow. Never commit to main; always write a meaningful commit message."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [git, version-control, collaboration]
---

# Git Workflow

Use this skill whenever working with git repositories.

## Branching

- `main` / `master` — always shippable, never commit directly
- `feat/<short-scope>` — new features (e.g. `feat/oauth-login`)
- `fix/<short-scope>` — bug fixes (e.g. `fix/token-refresh-race`)
- `chore/<short-scope>` — tooling, deps, configs (e.g. `chore/upgrade-pydantic`)
- `docs/<short-scope>` — documentation only
- `refactor/<short-scope>` — code restructure, no behavior change
- `test/<short-scope>` — adding tests only

## Commit Messages (Conventional Commits)

```
<type>(<scope>): <subject>

<body — explain why, not what>

<footer — breaking changes, issue refs>
```

**Types:** `feat`, `fix`, `docs`, `style`, ` refactor`, `test`, `chore`, `perf`, `build`, `ci`

**Rules:**
- Subject ≤ 72 chars, imperative mood ("add" not "added")
- No period at end of subject
- Body wraps at 72 chars
- Reference issues: `Fixes #123`, `Refs #456`

**Examples:**
```
feat(auth): add OAuth2 login with GitHub

Adds the /auth/github endpoint, callback handler, and user creation
flow. Token refresh handled via background task.

Closes #142
```

```
fix(api): handle null user_id in /profile endpoint

The endpoint was returning 500 when user_id was missing from the JWT.
Now returns 401 with a clear error message.

Fixes #287
```

## PR Flow

1. Branch from latest `main`: `git checkout main && git pull && git checkout -b feat/x`
2. Make small commits (one logical change each)
3. Rebase before pushing if `main` moved: `git fetch && git rebase origin/main`
4. Push: `git push -u origin feat/x`
5. Open PR with template:
   ```
   ## What
   <what this PR does>

   ## Why
   <motivation, context>

   ## How
   <approach, key decisions>

   ## Testing
   <how to verify>

   ## Checklist
   - [ ] Tests added/updated
   - [ ] Docs updated
   - [ ] CHANGELOG entry
   ```
6. Request review from at least one person
7. Address review comments with new commits (don't force-push during review)
8. Squash-merge or rebase-merge (per project convention)

## Anti-patterns

- ❌ `git commit -m "fix"` — meaningless message
- ❌ Committing directly to `main`
- ❌ Mixing unrelated changes in one PR
- ❌ Force-pushing to a shared branch
- ❌ Deleting branches before merge
- ❌ Huge PRs (>500 lines) without prior discussion
