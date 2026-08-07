# Aion Hand Security Audit

**Audit date:** 2026-08-07  
**Scope:** `main` at commit `f40f40f4dd2f21a8cc355c5b772b6bab8fa7b75c`  
**Focus:** tool execution, sandboxing, approvals, filesystem access, and command validation

## Executive summary

Aion Hand has useful security concepts (approval modes, a command validator, a sandbox runner, timeouts, and an audit log), but the current implementation should **not be treated as a security boundary**.

The highest-risk issue is in the Python sandbox: the implementation describes an allowlist of permitted modules, but the import hook actually permits every module except a denylist. This means code can import modules such as `os` and use OS-level functionality from the supposedly restricted Python sandbox.

A second major issue is architectural: the built-in `shell_command` tool executes through `asyncio.create_subprocess_shell()` directly in the tool registry. Its safety depends primarily on the tool approval mode, while the separate `SecurityManager`/`CommandValidator` is not automatically placed in that execution path. The default approval mode is `auto`, so an agent with access to the tool can execute arbitrary shell commands by default.

## Findings

### AION-SEC-001 — Python sandbox import allowlist is ineffective

**Severity:** Critical  
**Location:** `aion_core/security/sandbox.py`, `_build_sandbox_runner()`

The sandbox passes `SANDBOX_ALLOWED_MODULES`/`allowed_modules`, but `_restricted_import()` only rejects `_BLOCKED_MODULES`. Any module not on the denylist is imported successfully.

The implementation even states that the allowed module list is intended to restrict imports, while the actual import hook returns `_original_import()` for non-blocked modules.

**Impact:** sandboxed Python can reach modules such as `os`, `sys`, and other non-blocked standard-library functionality. This undermines the claimed sandbox boundary and can enable filesystem/process/environment access.

**Required fix:** implement a true default-deny import policy. Permit only the explicitly configured module roots plus the minimal modules required by the runner. Do not rely on a dangerous-module denylist as the sandbox boundary.

### AION-SEC-002 — `shell_command` is not enforced by the central sandbox policy

**Severity:** Critical  
**Location:** `aion_core/tools/registry.py`, `_handle_shell_command()` and tool registration

The tool directly calls `asyncio.create_subprocess_shell(command, ...)`. The registry's approval gate controls whether the tool runs, but the separate `CommandValidator` in `aion_core/security/sandbox.py` is not automatically applied here.

Because `AgentConfig.tool_approval_mode` defaults to `auto`, a normal agent session can reach an arbitrary shell execution primitive unless the host explicitly changes policy.

**Required fix:** route shell execution through one central security policy. The safe default should be deny/ask for dangerous operations, and command validation should happen immediately before execution. Prefer `create_subprocess_exec()` with an argument vector where possible; if a shell is unavoidable, enforce a dedicated policy and sandbox boundary.

### AION-SEC-003 — Blacklist-based command validation is not a reliable security boundary

**Severity:** High  
**Location:** `CommandValidator`

The validator uses regex deny patterns such as `rm -rf`, `curl | bash`, `crontab`, and `systemctl`. Shell syntax has many alternative ways to express operations, so a blacklist can be bypassed by aliases, command substitution, variable expansion, alternative utilities, quoting, interpreter invocation, or other shell features.

**Required fix:** replace blacklist-only protection with an allowlisted command model for privileged automation, or execute commands without a shell and validate the executable plus argument policy. Keep the blacklist only as defense-in-depth.

### AION-SEC-004 — Filesystem tools have no workspace boundary

**Severity:** High  
**Location:** `_handle_file_read()`, `_handle_file_write()`, `_handle_file_list()`

Paths are resolved with `Path(...).expanduser().resolve()`, but there is no configured workspace/root containment check. A tool can therefore target arbitrary readable/writable paths available to the process.

**Impact:** accidental or malicious access to configuration files, credentials, source trees, SSH material, or other user data.

**Required fix:** establish a workspace root and enforce `resolved_path == root` or `resolved_path.is_relative_to(root)` before filesystem operations. Add an explicit privileged escape hatch only when the host deliberately grants it.

### AION-SEC-005 — Dangerous operations default to permissive approval

**Severity:** High  
**Location:** `AgentConfig.tool_approval_mode`, tool registry

The default is `auto`, while tools such as `shell_command`, `code_execute`, and `file_write` are marked as dangerous/approval-required.

The approval mechanism is therefore present but permissive by default.

**Required fix:** default to `ask` for interactive deployments and `deny` for unattended deployments. Allow `auto` only through an explicit trusted-mode configuration.

### AION-SEC-006 — Audit records can contain sensitive tool parameters/results

**Severity:** Medium  
**Location:** `ToolResult`, registry execution log

The execution log records tool results, and tool results can contain file contents, command output, HTTP data, and other potentially sensitive material.

**Required fix:** add structured redaction, configurable maximum field lengths, secret-pattern filtering, and a policy for persistent vs in-memory audit storage.

## Recommended remediation order

1. **Fix AION-SEC-001** with a real default-deny Python import policy.
2. **Fix AION-SEC-002/003** by centralizing shell execution behind a security policy and preferring non-shell process execution.
3. **Fix AION-SEC-004** with workspace containment for filesystem tools.
4. **Fix AION-SEC-005** by changing secure defaults from `auto` to `ask`/`deny` depending on deployment mode.
5. **Fix AION-SEC-006** with redaction and bounded audit records.
6. Add regression tests for every finding and run them in CI.

## Important conclusion

Aion Hand has a promising security architecture, but the current implementation should be described as **security controls / guardrails rather than a hardened sandbox** until the findings above are addressed. In particular, Python subprocess isolation plus an import denylist is not equivalent to OS-level sandboxing or container isolation.
