# Aion Hand Security Hardening

This document tracks the security boundary required before Aion Hand should be marketed as a production autonomous agent.

## Current fixes on this branch

- Added `aion_core/security/secure_sandbox.py` with an explicit Python import allowlist.
- Added workspace path containment using canonical paths.
- Added argv-only process execution (`create_subprocess_exec`), avoiding shell parsing.
- Added sanitized environment construction.
- Added bounded stdout/stderr and process timeouts with process-group termination.
- Added regression tests for blocked imports and workspace traversal.

## Important limitation

`SecureSandbox.execute_python()` is a policy/containment layer, **not a complete OS sandbox**. Python itself is a powerful runtime. Production execution of hostile or unknown code must use an OS isolation boundary such as a dedicated container/VM with:

- non-root UID/GID
- read-only base filesystem
- a per-run writable workspace
- no host filesystem mounts except the workspace
- network disabled by default
- seccomp/AppArmor or equivalent syscall restrictions
- dropped Linux capabilities
- CPU, memory, process-count and disk quotas
- hard wall-clock timeout

The agent should never silently fall back to host execution when that isolation backend is unavailable.

## Product-readiness security gates

1. **Tool permissions:** dangerous tools default to `ask`; only explicitly safe read-only tools may default to automatic approval.
2. **Command execution:** accept structured argv, not arbitrary shell strings. If shell support is required, use a dedicated policy with an explicit command allowlist.
3. **Filesystem:** every file operation must resolve beneath an agent workspace and reject traversal/symlink escapes.
4. **Secrets:** redact API keys, authorization headers, cookies and tokens from logs and model-visible tool output.
5. **Network:** outbound network access must be an explicit capability, scoped by host/port policy.
6. **Subagents:** each subagent gets a bounded budget, timeout, tool capability set and cancellation path.
7. **Auditability:** record tool identity, policy decision, duration, status and a redacted parameter digest; never retain raw secrets by default.
8. **Reliability:** tool failures must be typed and recoverable; retries need exponential backoff and a maximum attempt count.
9. **Testing:** security regression tests run in CI on every pull request.
10. **Release:** publish a threat model, supported deployment model, security policy and reproducible test results before declaring a stable release.

## Recommended architecture

```text
LLM
  -> Agent Policy / Capability Resolver
  -> Approval Gate
  -> Tool Registry
      -> Read-only tools
      -> Network tools (scoped)
      -> Filesystem tools (workspace scoped)
      -> Execution broker
           -> OS/container isolation
  -> Redacted Audit Event
```

The goal is not to make Aion Hand merely powerful. The goal is to make autonomy **bounded, observable, reversible and predictable**.
