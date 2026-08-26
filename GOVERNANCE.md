# Aion Hand — Governance

This document describes how decisions are made in the Aion Hand project.

## Roles

### Contributors
Anyone who contributes code, docs, tests, issues, or discussions.
Contributors have:
- Read access to all repos (public)
- The ability to open PRs (merged at maintainers' discretion)
- The right to participate in discussions and design reviews

### Maintainers
Contributors with commit access to the main repository. Maintainers:
- Review and merge PRs
- Triage issues
- Have one vote in maintainer decisions
- Are expected to follow the Code of Conduct
- Are expected to contribute meaningfully for at least 6 months

Current maintainers:
- **@xdadik** — project founder, lead maintainer

### Lead maintainer
One maintainer who has final say in case of ties. Currently @xdadik.
The lead maintainer role is transferred by majority vote of maintainers.

## Decision-making process

### Small changes (bug fixes, docs, small features)
- Open a PR
- One maintainer approval required to merge
- No RFC needed

### Medium changes (new modules, significant refactors)
- Open an issue with `proposal` label first
- Get at least one maintainer to agree
- Open a PR
- Two maintainer approvals required to merge

### Large changes (breaking API changes, architectural shifts)
- Write an RFC (in `docs/rfcs/NNNN-title.md`)
- Post in GitHub Discussions for community input (1 week minimum)
- Maintainer vote: simple majority approves
- Update relevant ADRs (`docs/adr/`)
- Open PR(s)
- Three maintainer approvals required to merge

### Emergency changes (security fixes, data loss prevention)
- Lead maintainer can merge without review
- Must be reported in the next maintainer meeting
- Retroactive review required

## Voting

- Each maintainer has one vote
- Simple majority (>50%) for most decisions
- Two-thirds majority for: adding/removing maintainers, changing governance
- Lead maintainer breaks ties
- Abstentions don't count toward quorum

## Becoming a maintainer

To become a maintainer:
1. Be a contributor for at least 6 months
2. Have at least 10 merged PRs of significant scope
3. Be nominated by an existing maintainer
4. Pass a two-thirds majority vote of existing maintainers

## Stepping down

Maintainers may step down at any time by notifying the other maintainers.
After 6 months of inactivity, a maintainer is moved to emeritus status
(no commit access, but can be reinstated by simple vote).

## Code of Conduct enforcement

The Code of Conduct is enforced by maintainers. Reports go to the lead
maintainer (or, if the report is about the lead maintainer, to the
senior-most other maintainer). See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
for details.

## License & IP

All contributions are licensed under the project's [MIT License](./LICENSE).
Contributors retain their copyright but grant the project a perpetual,
worldwide, non-exclusive license to use, modify, and distribute their
contributions.

## Amendments

This governance document can be amended by a two-thirds majority vote
of maintainers, with at least one week's notice.
