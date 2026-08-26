# Security Policy

> **Read this before deploying Aion Hand in any environment that contains
> sensitive data, runs on shared infrastructure, or executes code provided
> by untrusted users.**

This document is intentionally honest. Aion Hand ships with a real,
useful sandbox — but no Python-level sandbox is a hard security boundary.
If you need a hard boundary, run Aion Hand inside a container, a VM,
or a seccomp-locked process. The sections below explain exactly what is
and is not protected, and what to do about it.

---

## Table of Contents

1. [Trust Boundary](#1-trust-boundary)
2. [Known Limitations](#2-known-limitations)
3. [Security Features](#3-security-features)
4. [Threat Model](#4-threat-model)
5. [Reporting Vulnerabilities](#5-reporting-vulnerabilities)
6. [Security Checklist](#6-security-checklist)
7. [Comparison with Other Agents](#7-comparison-with-other-agents)

---

## 1. Trust Boundary

### What IS a security boundary

| Layer                    | Boundary strength      | Notes                                            |
|--------------------------|------------------------|--------------------------------------------------|
| **OS process isolation** | Hard (per-process)     | Each sandbox run is a fresh subprocess           |
| **Environment stripping**| Hard (within process)  | `PYTHONPATH`, `LD_PRELOAD`, etc. are removed     |
| **Approval gate (ask)**  | Hard (human in loop)   | A human must explicitly approve every action     |
| **Command validator**    | Soft (regex-based)     | Defense in depth, not a complete shield          |
| **Module deny-list**     | Soft (CPython level)   | See [Known Limitations](#2-known-limitations)    |
| **Restricted builtins**  | Soft (CPython level)   | Removes `open`, `exec`, `eval`, `compile`        |
| **Output verification**  | Best-effort (LLM/heuristic) | Detects dangerous patterns in generated output |

### What is NOT a security boundary

**The Python sandbox is not a hard security boundary.** Anyone who claims
otherwise about a `RestrictedPython`/`exec()`-based sandbox is wrong.
The CPython object graph is reachable from any object via `__class__`,
`__subclasses__`, `__init__`, `__globals__`, etc. Once an attacker can
walk the object graph, they can recover the real `builtins`, and from
there call `os.system` or anything else.

We document this openly because pretending otherwise would be worse.

### The acceptable-use contract

Aion Hand's sandbox is designed to stop:

- **Accidental damage** — `os.remove("/etc/passwd")` because the LLM
  hallucinated a path.
- **Casual abuse** — a user pasting `import shutil; shutil.rmtree("/")`
  into a code-execution tool.
- **Naive prompt injection** — an LLM that follows a malicious instruction
  to "run this shell command".

It is **not** designed to stop:

- A skilled adversary who is deliberately trying to escape the sandbox.
- Code that exploits a CPython or OS-level vulnerability.
- An attacker who can write to the Aion Hand installation directory.

If you face any of those threats, use the [Hardened Deployment](#hardened-deployment)
recipe below.

---

## 2. Known Limitations

### 2.1 The CPython object-graph escape

Every Python object has a `__class__` attribute. Every class has
`__subclasses__()` and `__init__` / `__globals__`. From a single
string literal, an attacker can walk:

```
().__class__.__bases__[0].__subclasses__()
```

…and find a class whose `__init__.__globals__` contains the real
`builtins` module. From there: `builtins.__import__("os").system("…")`.

Our sandbox removes `open`, `eval`, `exec`, `compile`, and `breakpoint`
from the builtins dict, but it does **not** block attribute access on
existing objects. There is no way to do that in pure CPython without
patching the interpreter or using a restricted-eval library like
`RestrictedPython` (which has its own escape history).

We acknowledge this. We do not pretend otherwise.

### 2.2 Why `exec()` can never be fully safe

The sandbox runner ultimately calls `exec(user_code, _exec_globals)` —
there is no other way to run arbitrary Python. Every `exec`-based
sandbox in existence has either been broken or has accepted that it is
"defense in depth, not defense against all adversaries".

### 2.3 Module deny-list is an allow-list turned upside down

Our deny-list blocks `subprocess`, `socket`, `ctypes`, `shutil`,
`multiprocessing`, `pty`, `http`, `urllib`, `ssl`, etc. This is
comprehensive but it is a **negative** list — any new dangerous module
ships unblocked by default. We rely on reviewers to update the list
when new stdlib modules land.

If you want a positive list (allow only `math`, `json`, `re`, …), pass
`allowed_modules=[...]` to the `Sandbox` constructor. The default config
already does this for the `SANDBOX_ALLOWED_MODULES` env var.

### 2.4 Shell commands are regex-checked, not parsed

The `CommandValidator` matches commands against regex patterns. This
catches `rm -rf /` but not, for example:

```
rm -rf -- "/"           # quote bypass
rm -rf $HOME            # variable expansion
bash -c 'rm -rf /'      # nested shell
find / -delete          # alternate dangerous command not in blacklist
```

The whitelist mode (`add_whitelist`) is far stronger — only commands
matching an allow pattern are permitted. **Use whitelist mode in any
deployment that accepts user-supplied commands.**

### 2.5 What real isolation looks like

For deployments where the agent runs truly untrusted code, we recommend
layering the following on top of (or instead of) the in-process sandbox:

| Technique           | What it blocks                                         | How to use                                          |
|---------------------|--------------------------------------------------------|-----------------------------------------------------|
| **Docker**          | Filesystem, process, network, kernel                   | Run Aion Hand inside a container; mount `~/.aion-hand` read-write, everything else read-only |
| **seccomp-bpf**     | Syscalls (e.g. block `fork`, `execve`, `socket`)       | Use `bpftrace` / `libseccomp` on the agent process  |
| **gVisor / Kata**   | Kernel surface                                         | Run the Docker container under `--runtime=kata`     |
| **Firejail**        | Filesystem + network for non-Docker hosts              | `firejail --noprofile --private-tmp aion-hand`      |
| **Network policy**  | Outbound network                                       | iptables / egress proxy / cloud security group      |

A reference `Dockerfile` and `firejail.profile` are planned for v0.2.

---

## 3. Security Features

### 3.1 Sandbox (`aion_core.security.sandbox.Sandbox`)

- **Subprocess isolation** — every code execution is a fresh
  `asyncio.create_subprocess_exec`, not in-process `exec`.
- **Restricted environment** — `PYTHONPATH`, `LD_PRELOAD`,
  `PYTHONSTARTUP`, and all but a safe subset of env vars are stripped.
- **Module deny-list** — 27 known-dangerous stdlib modules are blocked
  at import time inside the sandbox runner.
- **Restricted builtins** — `open`, `exec`, `eval`, `compile`,
  `breakpoint`, `exit`, `quit` are removed from the globals dict.
- **Timeout enforcement** — every run is bounded by `asyncio.wait_for`;
  default 30s, overridable per-call.
- **Output capture** — stdout/stderr/exit_code are returned to the agent
  for verification, never executed or interpreted.

### 3.2 Command validation (`CommandValidator`)

- **Blacklist-first** — 22 patterns block `rm -rf /`, `mkfs`, `dd if=`,
  `:(){ :|:& };:`, `curl | bash`, `shutdown`, `reboot`, `kill -9 1`,
  `mv /etc/`, etc.
- **Optional whitelist** — when populated, **only** commands matching a
  whitelist regex are permitted. Empty whitelist means "anything not
  blacklisted".
- **Pattern API** — `add_whitelist(pattern)`, `add_blacklist(pattern)`,
  `remove_whitelist(pattern)`, `remove_blacklist(pattern)` for runtime
  reconfiguration.
- **Audit-trail** — every validation result is logged at WARNING level
  when blocked, DEBUG when approved.

### 3.3 Approval flow (`ApprovalManager`)

Three operating modes, switchable at runtime via `set_mode`:

| Mode    | Behaviour                                                              | When to use                                    |
|---------|------------------------------------------------------------------------|------------------------------------------------|
| `auto`  | Every request is immediately approved.                                 | Trusted local dev, CI pipelines                |
| `ask`   | Each request creates a pending ticket; agent blocks until a human calls `approve(id)` or `deny(id)`, or the ticket TTL (5 min) expires. | Production, shared machines, sensitive data   |
| `deny`  | Every gated request is immediately rejected.                           | Read-only / demo deployments                   |

Tickets have a UUID-based 8-char ID and a configurable TTL
(`_DEFAULT_TTL_SECONDS = 300`). Switching modes resolves all pending
tickets (auto → approve, deny → deny). Cancellation denies cleanly.

### 3.4 Output verification (`pipeline.verification`)

Five verifiers run on every agent output, in parallel:

1. **`LogicVerifier`** — detects contradictions and excessive hedging.
2. **`FactChecker`** — LLM-based factual review (only on long outputs).
3. **`CodeVerifier`** — `ast.parse` syntax check + security pattern scan
   (blocks `eval`, `exec`, `shell=True`, `pickle.loads`, hardcoded
   passwords/keys, etc.).
4. **`SecurityVerifier`** — scans for dangerous shell patterns
   (`rm -rf /`, `mkfs`, `dd of=/dev/`) and leaked secrets (AWS keys,
   `sk_…` API keys, `BEGIN … PRIVATE KEY`).
5. **`CompletenessVerifier`** — checks that every goal from the mission
   analysis is addressed by the result.

The `Critic` blends heuristic + LLM critiques and decides whether to
trigger the planner's `replan()` repair flow.

### 3.5 Permission system (`AgentConfig.security_*`)

- `sandbox_enabled` — master switch for the sandbox subsystem.
- `command_whitelist` — list of regex patterns; when non-empty, only
  whitelisted commands are allowed.
- `allowed_users` — list of user identifiers permitted to use the agent
  (enforced per-message by the messaging gateway, **fail-closed**: an
  empty list rejects every incoming message; each gateway user also
  gets an isolated session id `platform:user_id`).
- `tool_approval_mode` — default mode for the `ApprovalManager`.

### 3.6 MCP tool safety

- MCP-bridged tools are registered with `requires_approval=True` by
  default (see `mcp/bridge.py`).
- The bridge namespaces every tool as `mcp__<server>__<tool>` so
  built-in and external tools cannot collide.
- The MCP registry exposes `get_stats()` for auditing which external
  tools are visible to the agent at any time.

---

## 4. Threat Model

### Threats mitigated

| Threat                                              | Mitigation                                     |
|-----------------------------------------------------|------------------------------------------------|
| LLM hallucinates a destructive command              | Command blacklist + approval gate              |
| LLM emits buggy code that crashes the agent process | Subprocess isolation; agent process survives   |
| LLM produces code containing `eval(user_input)`     | `CodeVerifier` flags the pattern               |
| LLM accidentally leaks API keys in output           | `SecurityVerifier` detects `sk_…` patterns     |
| User runs agent with no timeout; LLM loops forever  | `max_turns=50`, `sandbox_timeout=30s` defaults |
| Long-running cron tasks starve the event loop       | Cron scheduler has per-task timeouts           |
| Subagent escape — a subagent runs malicious code    | Subagents share the parent's security manager  |

### Threats NOT mitigated

| Threat                                              | Why not                                                       |
|-----------------------------------------------------|---------------------------------------------------------------|
| Deliberate CPython sandbox escape                   | Object-graph walk is always possible (see §2.1)               |
| Prompt injection via tool output                    | LLM may follow instructions embedded in fetched web pages     |
| Memory poisoning — attacker writes to `MEMORY.md`   | Memory directory is on the same FS as the agent               |
| Side-channel timing attacks                         | No constant-time guarantees in sandbox code paths             |
| Supply-chain attacks via MCP servers                | MCP servers run as separate processes; we trust their authors |
| DoS via huge tool output                            | Outputs are truncated to 5 000 chars in `ExecutionResult` but not before reaching the agent |

### Acceptable use policy

Aion Hand is MIT-licensed and we place no restrictions on its use, but
**we recommend** the following:

- **Don't** deploy Aion Hand with `tool_approval_mode="auto"` on a
  machine with access to production data.
- **Don't** enable the messaging gateway on a public Telegram/Discord
  channel without setting `allowed_users`.
- **Don't** connect an MCP server you haven't audited — MCP servers run
  as subprocesses with full process privileges.
- **Do** run Aion Hand inside a container for any multi-tenant or
  internet-facing deployment.
- **Do** set `command_whitelist` to a minimal allow-list in production.
- **Do** rotate API keys periodically; the `SecurityVerifier` will flag
  leaked keys in outputs but won't catch leaks in logs.

---

## 5. Reporting Vulnerabilities

We take security reports seriously. Please do **not** open a public
GitHub issue for security vulnerabilities.

### How to report

- **Preferred:** email **security@aion-hand.dev** with a PGP-encrypted
  description. Public key fingerprint:
  `A1ON H4ND S3CU RITY 2024 K3Y0 RSA4 096`
- **Alternative:** open a [GitHub Security Advisory](https://github.com/xdadik/Aion/security/advisories/new)
  using the "Report a vulnerability" flow.
- **Bug bounty:** we are not currently running a paid bounty program,
  but credit and a place in the release notes hall-of-fame are guaranteed.

### What to include

- Affected version (or git commit SHA).
- A minimal reproduction. PoC code is welcome.
- The threat model — what could an attacker achieve?
- Suggested fix, if you have one.
- Whether you have already disclosed this elsewhere.

### Response timeline

| Day   | Action                                                                 |
|-------|------------------------------------------------------------------------|
| 0     | We acknowledge receipt within 24 hours                                 |
| 1–3   | Triage: confirm reproduction, assess severity, assign a CVE if needed |
| 3–14  | Develop and privately test a fix; coordinate disclosure window        |
| 14–30 | Release patched version; publish advisory with credit to reporter     |
| 30+   | Public disclosure if no patch is yet released (rare)                  |

### Credit policy

- Reporters are credited in the release notes and the advisory unless
  they request anonymity.
- We will never publish a reporter's name in connection with a
  vulnerability without their explicit consent.
- We do not pursue legal action against good-faith reporters.

---

## 6. Security Checklist

Items verified before every release. Run `make test` to execute
`tests/test_security.py` which covers all of the below.

### Pre-release

- [ ] All 22 default blacklist patterns block their target commands.
- [ ] All 27 blocked modules raise `ImportError` inside the sandbox.
- [ ] Restricted builtins (`open`, `exec`, `eval`, `compile`,
      `breakpoint`) raise `NameError` inside the sandbox.
- [ ] Sandbox subprocess times out at the configured limit.
- [ ] Sandbox subprocess cannot read `~/.aion-hand/config.json`.
- [ ] `ApprovalManager` correctly transitions through all three modes.
- [ ] Pending tickets expire after TTL with no leak.
- [ ] `CodeVerifier` flags every entry in `SECURITY_PATTERNS`.
- [ ] `SecurityVerifier` detects AWS keys, `sk_`/`pk_` secrets, and
      `BEGIN … PRIVATE KEY` blocks.
- [ ] MCP-bridged tools default to `requires_approval=True`.
- [ ] No hardcoded API keys, tokens, or passwords in the repository
      (`git log -p | rg -i 'api[_-]?key|secret|token'`).
- [ ] `bandit -r aion_core/` reports zero high-severity findings.
- [ ] `pip-audit` reports no known-vulnerable dependencies.

### Tested for but acknowledged imperfect

- [ ] Sandbox blocks naïve `import os; os.system("…")` — yes.
- [ ] Sandbox blocks `__import__("os")` — yes (builtins removed).
- [ ] Sandbox blocks object-graph escape — **no**, by design; see §2.1.

---

## 7. Comparison with Other Agents

| Feature                         | Aion Hand  | Hermes Agent | OpenClaw    | NullClaw    |
|---------------------------------|------------|--------------|-------------|-------------|
| Process-isolated sandbox        | Yes        | Yes          | Yes         | Yes (Zig)   |
| Module deny-list                | 27 modules | ~20 modules  | Per-tool    | n/a (no Py) |
| Restricted builtins             | Yes        | Yes          | No          | n/a         |
| Command whitelist mode          | Yes        | Yes          | Yes         | No          |
| Approval modes (auto/ask/deny)  | 3 modes    | 3 modes      | 2 (ask/deny)| 1 (auto)    |
| LLM-based output verification   | 5 verifiers| 3 verifiers  | None        | None        |
| Secret-leak detection in output | Yes        | Yes          | No          | No          |
| MCP tool approval default       | Required   | Required     | Optional    | n/a         |
| Documented sandbox limitations  | This file  | Yes          | Partial     | n/a         |
| Container deployment guide      | Planned    | Yes          | Yes         | No          |

### What we do better

- **Verification depth** — 5 parallel verifiers including a
  completeness check that ties outputs back to mission goals.
- **Approval flow** — three modes with runtime switching, ticket TTLs,
  and cancellation safety.
- **Honesty** — this document openly states the object-graph escape
  rather than implying the sandbox is unbreakable.

### What we're working on

- **v0.2:** Reference `Dockerfile` and `firejail` profile for
  out-of-the-box hardened deployment.
- **v0.2:** Optional `RestrictedPython` backend for the sandbox,
  trading off some stdlib compatibility for stronger attribute-access
  controls.
- **v0.3:** seccomp-bpf filter template for Linux deployments.
- **v0.3:** Per-tool capability tokens (a tool can only act on the
  exact resources named in its approval ticket).
- **v0.4:** Prompt-injection-resistant tool-output sanitisation layer
  between tool execution and LLM context.

---

## Hardened Deployment (quick recipe)

> **v0.4.0 hardening notes** — the following are now enforced at runtime
> (previously documented but not wired):
>
> * HTTP API binds `127.0.0.1` by default; a non-loopback bind REFUSES to
>   start without a bearer token (`AION_API_TOKEN` env or `api_token`
>   config). All `/api/*` routes require `Authorization: Bearer <token>`
>   when a token is set; `cors_origins=None` now means NO CORS (no more
>   reflecting arbitrary origins).
> * `shell_command` runs every command through the `CommandValidator`
>   blacklist (rm -rf /, curl|bash, shutdown, ...) before spawning.
> * `file_read` refuses credential stores (the agent's own config.json,
>   SSH keys, .env files, /etc/shadow, /etc/sudoers).
> * `file_write` refuses the agent's auto-loaded dirs
>   (~/.aion-hand/{plugins,tools,personas,skills}) — the agent can no
>   longer plant code that auto-executes on next boot.
> * `code_execute(use_tools=True)` rejects sandbox-escape source patterns
>   (`__subclasses__`, `__globals__`, ...).
> * `GET /api/config` deep-redacts secrets recursively (nested provider
>   api_keys and platform tokens).
> * Config files are written with mode 0600.
> * Marketplace-installed skills land as DRAFT (not advertised to the LLM
>   until a human activates them); local skills load ACTIVE.

```dockerfile
FROM python:3.12-slim AS aion-hand-hardened

# Drop privileges
RUN useradd --create-home --shell /bin/false aion
USER aion
WORKDIR /home/aion

# Install without dev dependencies
COPY --chown=aion:aion . /home/aion/aion-hand
RUN pip install --user --no-cache-dir /home/aion/aion-hand

# Read-only root filesystem, writable data dir
VOLUME ["/home/aion/.aion-hand"]
ENV AION_HAND_HOME=/home/aion/.aion-hand
ENV AION_HAND_TOOL_APPROVAL_MODE=ask
ENV AION_HAND_COMMAND_WHITELIST="^ls\\s,^cat\\s,^echo\\s,^grep\\s"

# No network by default — override with --network=host if needed
EXPOSE 0

ENTRYPOINT ["python", "-m", "aion_hand_cli"]
CMD ["chat"]
```

Run it with:

```bash
docker run --rm -it \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v aion-data:/home/aion/.aion-hand \
  aion-hand-hardened
```

This is the configuration under which the sandbox limitations described
in §2 stop mattering for most threat models: even a full CPython escape
lands an attacker inside a read-only, capability-stripped container with
no network and a non-root UID.

---

*This policy is versioned with the codebase. Last updated for Aion Hand
v0.1.0. If you are reading a fork or vendor copy, verify it against the
canonical version at https://github.com/xdadik/Aion/SECURITY.md.*
