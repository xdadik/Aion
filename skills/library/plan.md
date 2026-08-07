---
name: plan
description: "Plan mode: write an actionable markdown plan to .aion/plans/, no execution. Bite-sized tasks, exact paths, complete code."
version: 2.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [planning, plan-mode, implementation, workflow, design]
  related_skills: [test-driven-development, systematic-debugging, code-review]
---

# Plan Mode

Use this skill when the user wants a plan instead of execution.

## Core behavior

For this turn, you are **planning only**.

- Do NOT implement code.
- Do NOT edit project files except the plan markdown file.
- Do NOT run mutating terminal commands, commit, push, or perform external actions.
- You MAY inspect the repo or other context with read-only commands/tools.
- Your deliverable is a markdown plan saved under `.aion/plans/`.

## Output requirements

Write a markdown plan that is concrete and actionable.

Include, when relevant:
- **Goal** — one-sentence statement of what success looks like
- **Current context / assumptions** — what's already true, what you're assuming
- **Proposed approach** — high-level strategy, with alternatives considered
- **Step-by-step plan** — each step small enough to commit individually
- **Files likely to change** — exact paths
- **Tests / validation** — what proves each step works
- **Risks, tradeoffs, open questions**

If the task is code-related, include exact file paths, likely test targets,
and verification steps.

## Save location

Save the plan with `write_file` under:
- `.aion/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

If the runtime provides a specific target path, use that.
Otherwise create a sensible timestamped filename yourself.

## Interaction style

- If the request is clear, write the plan directly.
- If no instruction accompanies `/plan`, infer the task from current context.
- If genuinely underspecified, ask ONE brief clarifying question.
- After saving, reply briefly with what you planned and the saved path.

## Examples

**User:** "plan adding OAuth to the API"
**You:** inspect repo (read_file, list_dir) → write `.aion/plans/2026-08-08_143000-add-oauth.md` → reply with summary + path

**User:** "/plan"
**You:** "What would you like me to plan?" (one question, not a survey)
