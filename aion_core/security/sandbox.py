#!/usr/bin/env python3
"""
Aion Hand - Security Module
============================

Sandboxed execution, command validation, and tool approval flow for the
Aion Hand AI agent framework.

Security system inspired by:
  - OpenClaw:  Command approval gates and container isolation for tools
  - Hermes:    Security model with layered permission checks and audit trails
  - MCP:       Principle of least privilege for tool access

Classes:
  - CommandValidator   – whitelist / blacklist regex-based command safety checks
  - ApprovalManager    – async approval flow (auto / ask / deny modes)
  - Sandbox            – lightweight sandboxed code and shell execution
  - SecurityManager    – central facade combining all security components
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, UTC
from enum import Enum
from typing import Any

logger = logging.getLogger("aion_hand.security.sandbox")


# ======================================================================
# Constants
# ======================================================================

_DEFAULT_BLACKLIST_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",          # Dangerous recursive removal
    r"rm\s+-rf\s+\.",         # Remove current directory tree
    r"mkfs",                   # Format filesystem
    r"dd\s+if=",               # Low-level disk clone/write
    r">\s*/dev/",              # Direct block-device writes
    r"chmod\s+777",            # World-writable permissions
    r"chown\s+-R",             # Recursive ownership change
    r"curl.*\|\s*bash",        # Remote code execution via curl
    r"curl.*\|\s*sh",          # Remote code execution via curl (sh)
    r"wget.*\|\s*sh",          # Remote code execution via wget
    r"wget.*\|\s*bash",        # Remote code execution via wget (bash)
    r":\(\)\s*\{\s*:\|:",     # Fork bomb pattern
    r"shutdown",               # System shutdown
    r"reboot",                 # System reboot
    r"init\s+0",               # Halt system
    r"passwd",                 # Password change
    r"kill\s+-9\s+1",          # Kill init
    r">\s*/etc/",              # Write to critical system config
    r"mv\s+/etc/",             # Move system config files
    r"crontab",                # Cron job manipulation
    r"systemctl\s+(stop|disable|mask)",  # Disable critical services
]

_DEFAULT_ALLOWED_MODULES: list[str] = [
    "math",
    "json",
    "re",
    "datetime",
    "collections",
    "itertools",
    "statistics",
    "fractions",
    "decimal",
    "string",
    "hashlib",
    "hmac",
    "base64",
    "functools",
    "operator",
    "textwrap",
    "unicodedata",
]

_DEFAULT_TIMEOUT: int = 30


# ======================================================================
# Approval Mode
# ======================================================================


class ApprovalMode(str, Enum):
    """How the approval manager handles incoming tool/command requests."""

    AUTO = "auto"   # Automatically approve – no gate
    ASK = "ask"     # Pause and wait for explicit human approval
    DENY = "deny"   # Block everything that requires approval


# ======================================================================
# Command Validator
# ======================================================================


class CommandValidator:
    """Validates shell commands against configurable whitelist and blacklist
    patterns.

    The validator first checks the command against *blacklist* patterns.  If
    any blacklist regex matches, the command is **rejected** immediately.
    Next, if any *whitelist* patterns are configured, the command must match at
    least one whitelist entry to be considered safe.  An empty whitelist means
    "all non-blacklisted commands are allowed".

    Example::

        validator = CommandValidator()
        validator.add_whitelist(r"^ls\\s")
        validator.add_whitelist(r"^cat\\s")
        safe, reason = validator.validate("ls -la /tmp")
        assert safe is True
    """

    def __init__(
        self,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
    ) -> None:
        self._whitelist_patterns: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in (whitelist or [])
        ]
        self._blacklist_patterns: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in (blacklist or _DEFAULT_BLACKLIST_PATTERNS)
        ]
        logger.debug(
            "CommandValidator initialised with %d whitelist and %d blacklist patterns",
            len(self._whitelist_patterns),
            len(self._blacklist_patterns),
        )

    # -- Public API -------------------------------------------------------

    def validate(self, command: str) -> tuple[bool, str]:
        """Validate a shell command string.

        Returns:
            A ``(is_safe, reason)`` tuple where *is_safe* is ``True`` when the
            command passes all checks, and *reason* is a human-readable
            explanation.
        """
        if not command or not command.strip():
            return False, "Empty command"

        # Strip leading/trailing whitespace for matching purposes
        stripped = command.strip()

        # --- Blacklist check (reject first) ------------------------------
        for pattern in self._blacklist_patterns:
            if pattern.search(stripped):
                reason = (
                    f"Command matches blacklisted pattern '{pattern.pattern}': "
                    f"{command!r}"
                )
                logger.warning("Command blocked: %s", reason)
                return False, reason

        # --- Whitelist check (if configured) -----------------------------
        if self._whitelist_patterns:
            matched = False
            for pattern in self._whitelist_patterns:
                if pattern.search(stripped):
                    matched = True
                    break
            if not matched:
                reason = (
                    f"Command does not match any whitelisted pattern: {command!r}"
                )
                logger.warning("Command blocked: %s", reason)
                return False, reason

        logger.debug("Command approved: %r", command)
        return True, "Command passed validation"

    def add_whitelist(self, pattern: str) -> None:
        """Add a regex pattern to the whitelist.

        Commands must match at least one whitelist pattern when the whitelist
        is non-empty.
        """
        compiled = re.compile(pattern, re.IGNORECASE)
        self._whitelist_patterns.append(compiled)
        logger.info("Whitelist pattern added: %s", pattern)

    def add_blacklist(self, pattern: str) -> None:
        """Add a regex pattern to the blacklist.

        Any command matching a blacklist pattern is immediately rejected.
        """
        compiled = re.compile(pattern, re.IGNORECASE)
        self._blacklist_patterns.append(compiled)
        logger.info("Blacklist pattern added: %s", pattern)

    def remove_whitelist(self, pattern: str) -> bool:
        """Remove a whitelist pattern by its raw string. Returns ``True`` if
        found and removed, ``False`` otherwise."""
        for i, pat in enumerate(self._whitelist_patterns):
            if pat.pattern == pattern:
                self._whitelist_patterns.pop(i)
                logger.info("Whitelist pattern removed: %s", pattern)
                return True
        return False

    def remove_blacklist(self, pattern: str) -> bool:
        """Remove a blacklist pattern by its raw string. Returns ``True`` if
        found and removed, ``False`` otherwise."""
        for i, pat in enumerate(self._blacklist_patterns):
            if pat.pattern == pattern:
                self._blacklist_patterns.pop(i)
                logger.info("Blacklist pattern removed: %s", pattern)
                return True
        return False

    # -- Introspection ----------------------------------------------------

    @property
    def whitelist_patterns(self) -> list[str]:
        """Return raw whitelist pattern strings."""
        return [p.pattern for p in self._whitelist_patterns]

    @property
    def blacklist_patterns(self) -> list[str]:
        """Return raw blacklist pattern strings."""
        return [p.pattern for p in self._blacklist_patterns]


# ======================================================================
# Approval Manager
# ======================================================================


class ApprovalManager:
    """Manages tool / command approval flow with three operating modes.

    Modes:
      - ``auto`` – all requests are approved immediately (useful for trusted
        environments or CI pipelines).
      - ``ask``  – each request creates a pending ticket that must be
        explicitly approved or denied by a human operator.
      - ``deny`` – all requests that enter the approval gate are rejected.

    Pending approvals have a configurable TTL; expired tickets are
    automatically denied.

    Example::

        mgr = ApprovalManager(mode="ask")
        approved = await mgr.request_approval(
            tool_name="file_delete",
            params={"path": "/tmp/old_data"},
            reason="Cleaning up temporary files",
        )
    """

    _DEFAULT_TTL_SECONDS: int = 300  # 5 minutes

    def __init__(self, mode: str = "auto") -> None:
        try:
            self._mode = ApprovalMode(mode)
        except ValueError:
            logger.warning("Unknown approval mode %r – falling back to 'auto'", mode)
            self._mode = ApprovalMode.AUTO

        # approval_id -> {tool_name, params, reason, created_at, status}
        self._pending_approvals: dict[str, dict] = {}
        self._approved_commands: set[str] = set()
        self._denied_commands: set[str] = set()
        self._ttl: int = self._DEFAULT_TTL_SECONDS

        logger.info("ApprovalManager initialised in %s mode", self._mode.value)

    # -- Public API -------------------------------------------------------

    async def request_approval(
        self,
        tool_name: str,
        params: dict[str, Any],
        reason: str,
    ) -> bool:
        """Request approval for a tool / command execution.

        In ``auto`` mode the request is immediately approved.  In ``deny``
        mode it is immediately rejected.  In ``ask`` mode a pending approval
        ticket is created; the method **waits** (with periodic timeout cleanup)
        until a human calls :meth:`approve` or :meth:`deny`, or the ticket
        expires.

        Returns:
            ``True`` if the execution was approved, ``False`` otherwise.
        """
        approval_id = str(uuid.uuid4())[:8]
        command_key = f"{tool_name}:{json_dumps_safe(params)}"

        # Fast-path: already explicitly approved or denied this exact request
        if command_key in self._approved_commands:
            logger.debug("Pre-approved command key: %s", command_key)
            return True
        if command_key in self._denied_commands:
            logger.debug("Pre-denied command key: %s", command_key)
            return False

        # Mode-specific handling
        if self._mode == ApprovalMode.AUTO:
            logger.info(
                "AUTO-approve tool=%s params=%s reason=%s",
                tool_name,
                params,
                reason,
            )
            self._approved_commands.add(command_key)
            return True

        if self._mode == ApprovalMode.DENY:
            logger.warning(
                "DENY tool=%s params=%s reason=%s",
                tool_name,
                params,
                reason,
            )
            self._denied_commands.add(command_key)
            return False

        # ASK mode – create ticket and wait
        self._pending_approvals[approval_id] = {
            "tool_name": tool_name,
            "params": params,
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pending",
            "command_key": command_key,
        }

        logger.info(
            "ASK – pending approval %s for tool=%s reason=%s",
            approval_id,
            tool_name,
            reason,
        )

        # Wait loop – poll every 0.5s, clean expired tickets
        try:
            while True:
                # Check expiry
                ticket = self._pending_approvals.get(approval_id)
                if ticket is None:
                    # Ticket was cleaned up (expired)
                    return False

                if ticket["status"] == "approved":
                    self._approved_commands.add(command_key)
                    del self._pending_approvals[approval_id]
                    return True

                if ticket["status"] == "denied":
                    self._denied_commands.add(command_key)
                    del self._pending_approvals[approval_id]
                    return False

                # Cleanup expired tickets
                self._cleanup_expired()

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # If the waiting coroutine is cancelled, clean up and deny
            self._pending_approvals.pop(approval_id, None)
            logger.info("Approval wait cancelled for %s", approval_id)
            return False

    def approve(self, approval_id: str) -> bool:
        """Explicitly approve a pending request by its ID.

        Returns ``True`` if the ticket was found and updated, ``False`` if it
        did not exist or was already resolved.
        """
        ticket = self._pending_approvals.get(approval_id)
        if ticket is None:
            logger.warning("approve() called for unknown ID %s", approval_id)
            return False
        if ticket["status"] != "pending":
            logger.warning(
                "approve() called on already-resolved ticket %s (status=%s)",
                approval_id,
                ticket["status"],
            )
            return False
        ticket["status"] = "approved"
        logger.info("Approval %s granted for tool=%s", approval_id, ticket["tool_name"])
        return True

    def deny(self, approval_id: str) -> bool:
        """Explicitly deny a pending request by its ID.

        Returns ``True`` if the ticket was found and updated, ``False`` if it
        did not exist or was already resolved.
        """
        ticket = self._pending_approvals.get(approval_id)
        if ticket is None:
            logger.warning("deny() called for unknown ID %s", approval_id)
            return False
        if ticket["status"] != "pending":
            logger.warning(
                "deny() called on already-resolved ticket %s (status=%s)",
                approval_id,
                ticket["status"],
            )
            return False
        ticket["status"] = "denied"
        logger.info("Approval %s denied for tool=%s", approval_id, ticket["tool_name"])
        return True

    def set_mode(self, mode: str) -> None:
        """Switch the approval mode at runtime.

        When switching away from ``ask``, all pending tickets are automatically
        resolved: approved if switching to ``auto``, denied if switching to
        ``deny``.
        """
        try:
            new_mode = ApprovalMode(mode)
        except ValueError:
            logger.warning("Unknown mode %r – ignoring", mode)
            return

        old_mode = self._mode
        self._mode = new_mode

        # Resolve pending tickets based on new mode
        if new_mode == ApprovalMode.AUTO:
            for tid, ticket in list(self._pending_approvals.items()):
                if ticket["status"] == "pending":
                    ticket["status"] = "approved"
                    self._approved_commands.add(ticket["command_key"])
        elif new_mode == ApprovalMode.DENY:
            for tid, ticket in list(self._pending_approvals.items()):
                if ticket["status"] == "pending":
                    ticket["status"] = "denied"
                    self._denied_commands.add(ticket["command_key"])

        logger.info("Approval mode changed: %s -> %s", old_mode.value, new_mode.value)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return a list of all currently pending approval tickets."""
        self._cleanup_expired()
        return [
            {
                "approval_id": tid,
                "tool_name": ticket["tool_name"],
                "params": ticket["params"],
                "reason": ticket["reason"],
                "created_at": ticket["created_at"],
                "status": ticket["status"],
            }
            for tid, ticket in self._pending_approvals.items()
            if ticket["status"] == "pending"
        ]

    # -- Internal --------------------------------------------------------

    def _cleanup_expired(self) -> None:
        """Remove tickets whose TTL has elapsed."""
        now = datetime.now(UTC)
        expired: list[str] = []
        for tid, ticket in self._pending_approvals.items():
            try:
                created = datetime.fromisoformat(ticket["created_at"])
            except (ValueError, TypeError):
                expired.append(tid)
                continue
            if (now - created).total_seconds() > self._ttl:
                ticket["status"] = "denied"
                expired.append(tid)
                logger.info("Approval ticket %s expired", tid)

        for tid in expired:
            self._pending_approvals.pop(tid, None)


# ======================================================================
# Sandbox
# ======================================================================


class Sandbox:
    """Lightweight sandbox for code execution safety.

    Provides two execution backends:

    * **Python sandbox** – runs arbitrary Python code in a subprocess with a
      restricted set of importable modules and no access to ``os``,
      ``subprocess``, ``socket``, etc.
    * **Shell sandbox** – validates commands through a
      :class:`CommandValidator` before executing them in a subprocess with
      limited environment variables.

    Both backends enforce a configurable execution timeout.

    Example::

        sandbox = Sandbox(allowed_modules=["math", "json"], timeout=10)
        result = await sandbox.execute_python("import math; print(math.factorial(10))")
        assert result["exit_code"] == 0
    """

    def __init__(
        self,
        allowed_modules: list[str] | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._allowed_modules: list[str] = allowed_modules or list(_DEFAULT_ALLOWED_MODULES)
        self._timeout: int = timeout
        self._validator = CommandValidator()
        self._execution_count: int = 0
        self._total_time: float = 0.0

        logger.info(
            "Sandbox initialised: %d allowed modules, timeout=%ds",
            len(self._allowed_modules),
            self._timeout,
        )

    # -- Public API -------------------------------------------------------

    async def execute_python(
        self,
        code: str,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute Python code in a sandboxed subprocess.

        The subprocess environment restricts which modules can be imported
        via the ``SANDBOX_ALLOWED_MODULES`` environment variable.  The
        sandbox runner script enforces this at import time.

        Args:
            code: Python source code to execute.
            timeout: Override the default timeout (seconds).

        Returns:
            A dict with keys ``exit_code``, ``stdout``, ``stderr``,
            ``timed_out``, and ``duration``.
        """
        import time as _time

        effective_timeout = timeout if timeout is not None else self._timeout
        effective_timeout = max(effective_timeout, 1)  # Minimum 1 second
        start = _time.monotonic()

        # Build the sandbox runner script
        allowed_str = ",".join(self._allowed_modules)
        runner_script = _build_sandbox_runner(allowed_str, code)

        # Build a restricted environment
        env = self._build_restricted_env()

        self._execution_count += 1

        try:
            process = await asyncio.create_subprocess_exec(
                sys_executable(),
                "-c",
                runner_script,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )

            duration = _time.monotonic() - start
            self._total_time += duration

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            result: dict[str, Any] = {
                "exit_code": process.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "timed_out": False,
                "duration": round(duration, 4),
            }

            if process.returncode != 0:
                logger.warning(
                    "Sandbox Python execution failed (exit=%d): %s",
                    process.returncode,
                    stderr_str[:500],
                )
            else:
                logger.debug(
                    "Sandbox Python execution OK (duration=%.3fs)", duration
                )

            return result

        except TimeoutError:
            duration = _time.monotonic() - start
            self._total_time += duration
            logger.warning(
                "Sandbox Python execution timed out after %ds", effective_timeout
            )
            # Kill the process if still running
            if process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass

            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {effective_timeout}s",
                "timed_out": True,
                "duration": round(duration, 4),
            }

        except Exception as exc:
            duration = _time.monotonic() - start
            self._total_time += duration
            logger.error("Sandbox Python execution error: %s", exc)
            return {
                "exit_code": -2,
                "stdout": "",
                "stderr": str(exc),
                "timed_out": False,
                "duration": round(duration, 4),
            }

    async def execute_shell(
        self,
        command: str,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute a shell command with prior validation.

        The command is first passed through the :class:`CommandValidator`.  If
        validation fails the command is not executed and the result dict
        contains ``validation_error``.

        Args:
            command: Shell command string.
            timeout: Override the default timeout (seconds).

        Returns:
            A dict with keys ``exit_code``, ``stdout``, ``stderr``,
            ``timed_out``, ``duration``, and optionally ``validation_error``.
        """
        import time as _time

        effective_timeout = timeout if timeout is not None else self._timeout
        effective_timeout = max(effective_timeout, 1)

        # Validate first
        is_safe, reason = self._validator.validate(command)
        if not is_safe:
            logger.warning("Shell command blocked by validator: %s", reason)
            return {
                "exit_code": -3,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "duration": 0.0,
                "validation_error": reason,
            }

        start = _time.monotonic()
        env = self._build_restricted_env()

        self._execution_count += 1

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )

            duration = _time.monotonic() - start
            self._total_time += duration

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            result: dict[str, Any] = {
                "exit_code": process.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "timed_out": False,
                "duration": round(duration, 4),
            }

            if process.returncode != 0:
                logger.warning(
                    "Sandbox shell command failed (exit=%d): %s",
                    process.returncode,
                    stderr_str[:500],
                )
            else:
                logger.debug(
                    "Sandbox shell command OK (duration=%.3fs)", duration
                )

            return result

        except TimeoutError:
            duration = _time.monotonic() - start
            self._total_time += duration
            logger.warning(
                "Sandbox shell command timed out after %ds", effective_timeout
            )
            if process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass

            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {effective_timeout}s",
                "timed_out": True,
                "duration": round(duration, 4),
            }

        except Exception as exc:
            duration = _time.monotonic() - start
            self._total_time += duration
            logger.error("Sandbox shell execution error: %s", exc)
            return {
                "exit_code": -2,
                "stdout": "",
                "stderr": str(exc),
                "timed_out": False,
                "duration": round(duration, 4),
            }

    # -- Introspection ----------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return execution statistics."""
        return {
            "execution_count": self._execution_count,
            "total_duration": round(self._total_time, 4),
            "avg_duration": (
                round(self._total_time / self._execution_count, 4)
                if self._execution_count > 0
                else 0.0
            ),
            "allowed_modules": list(self._allowed_modules),
            "default_timeout": self._timeout,
        }

    # -- Internal --------------------------------------------------------

    @staticmethod
    def _build_restricted_env() -> dict[str, str]:
        """Construct a minimal environment for sandboxed subprocesses.

        Removes variables that could be used to escape the sandbox (e.g.
        ``PYTHONPATH``, ``LD_PRELOAD``, ``PYTHONSTARTUP``) and sets a
        restrictive ``PATH``.
        """
        # Start with a minimal safe set
        env: dict[str, str] = {
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "TERM": "dumb",
        }

        # Copy through a small allowlist of safe env vars
        _safe_vars = {"USER", "LOGNAME", "SHELL", "TZ"}
        for var in _safe_vars:
            val = os.environ.get(var)
            if val is not None:
                env[var] = val

        return env


# ======================================================================
# Sandbox Runner Builder
# ======================================================================


# Modules explicitly blocked in the sandbox (dangerous / system-access).
# CPython internal modules (starting with '_') and encoding modules are
# always allowed so that standard-library transitive imports work.
# Note: modules that are widely used internally (e.g. 'os' is imported
# by many stdlib modules) are NOT blocked here; protection comes from
# the restricted builtins (no open/exec/eval/compile) and subprocess
# environment isolation.
_BLOCKED_MODULES: set = {
    "subprocess",
    "shutil",
    "socket",
    "ctypes",
    "multiprocessing",
    "signal",
    "pty",
    "fcntl",
    "termios",
    "tty",
    "pipes",
    "webbrowser",
    "pdb",
    "runpy",
    "antigravity",
    "code",
    "codeop",
    "compileall",
    "distutils",
    "setuptools",
    "pip",
    "pkg_resources",
    "pathlib",
    "tempfile",
    "glob",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "ssl",
}


def _build_sandbox_runner(allowed_modules_str: str, user_code: str) -> str:
    """Build a self-contained Python script that restricts imports.

    Uses a deny-list for dangerous modules.  Any module whose top-level
    name starts with ``_`` (CPython internal) or is in the
    *allowed_modules_str* set is permitted.  User code is executed via
    ``exec()`` with a restricted ``__builtins__`` (no ``open``, ``eval``,
    ``exec``, ``compile``, ``breakpoint``).
    """
    blocked_repr = repr(sorted(_BLOCKED_MODULES))
    allowed_repr = repr(allowed_modules_str)
    comma_repr = repr(",")
    dot_repr = repr(".")
    user_code_repr = repr(user_code)

    lines = [
        "import importlib, sys, types",
        "",
        "# -- Module import restriction (deny-list) --",
        "_BLOCKED = " + blocked_repr,
        "",
        "_original_import = __builtins__.__import__ if isinstance(__builtins__, dict) else __import__",
        "",
        "def _restricted_import(name, *args, **kwargs):",
        "    top = name.split(" + dot_repr + ")[0]",
        "    # Allow CPython internal modules (prefix _)",
        "    if top.startswith(" + repr("_") + "):",
        "        return _original_import(name, *args, **kwargs)",
        "    # Allow encoding-related modules (needed by print/stdout)",
        "    if top in (" + repr("encodings") + ", " + repr("codecs") + ", " + repr("locale") + "):",
        "        return _original_import(name, *args, **kwargs)",
        "    # Block dangerous modules",
        "    if top in _BLOCKED:",
        "        raise ImportError(",
        "            \"Sandbox restriction: importing \" + repr(name) + \" is blocked.\"",
        "        )",
        "    return _original_import(name, *args, **kwargs)",
        "",
        "if isinstance(__builtins__, dict):",
        "    __builtins__[\"__import__\"] = _restricted_import",
        "else:",
        "    __builtins__.__import__ = _restricted_import",
        "",
        "# -- Restricted builtins --",
        "_safe_builtins = dict(vars(__builtins__)) if isinstance(__builtins__, dict) else dict(vars(__builtins__))",
        "_rm = [\"open\", \"exec\", \"eval\", \"compile\",",
        "         \"breakpoint\", \"exit\", \"quit\"]",
        "for _k in list(_safe_builtins):",
        "    if _k in _rm:",
        "        del _safe_builtins[_k]",
        "# Keep the restricted __import__ in builtins so 'import' works",
        "_safe_builtins[\"__import__\"] = _restricted_import",
        "",
        "# -- Pre-import allowed extra modules --",
        "_ALLOWED_EXTRA = set(" + allowed_repr + ".split(" + comma_repr + "))",
        "",
        "# -- User code --",
        "try:",
        "    _exec_globals = {\"__builtins__\": _safe_builtins}",
        "    for _mod_name in _ALLOWED_EXTRA:",
        "        try:",
        "            _exec_globals[_mod_name] = _original_import(_mod_name)",
        "        except ImportError:",
        "            pass",
        "",
        "    exec(" + user_code_repr + ", _exec_globals)",
        "",
        "except Exception as _e:",
        "    print(str(_e), file=sys.stderr)",
        "    sys.exit(1)",
    ]

    return "\n".join(lines) + "\n"


# ======================================================================
# Security Manager
# ======================================================================


class SecurityManager:
    """Central security manager that combines all security components.

    Provides a single entry point for command validation, tool approval, and
    sandboxed execution.  Designed to be instantiated once per agent and
    shared across the tool registry, agent loop, and orchestration layers.

    Example::

        from types import SimpleNamespace

        config = SimpleNamespace(
            command_whitelist=[r"^ls\\s", r"^cat\\s", r"^echo\\s"],
            tool_approval_mode="ask",
            sandbox_timeout=30,
        )

        security = SecurityManager(config)
        safe, reason = await security.check_command("ls -la /tmp")
        approved = await security.request_tool_approval(
            "file_delete", {"path": "/tmp/old"}, "Cleanup"
        )
        result = await security.execute_sandboxed("print(2 + 2)")
    """

    def __init__(self, config: Any = None) -> None:
        cfg = config or _empty_config()

        self._validator = CommandValidator(
            whitelist=getattr(cfg, "command_whitelist", None),
            blacklist=getattr(cfg, "command_blacklist", None),
        )
        self._approval = ApprovalManager(
            mode=getattr(cfg, "tool_approval_mode", "auto"),
        )
        self._sandbox = Sandbox(
            allowed_modules=getattr(cfg, "sandbox_allowed_modules", None),
            timeout=getattr(cfg, "sandbox_timeout", _DEFAULT_TIMEOUT),
        )

        # Audit log – lightweight in-memory ring buffer
        self._audit_log: list[dict[str, Any]] = []
        self._max_audit_entries: int = getattr(cfg, "max_audit_entries", 1000)

        logger.info("SecurityManager initialised")

    # -- Public API -------------------------------------------------------

    async def check_command(self, command: str) -> tuple[bool, str]:
        """Validate a command through the :class:`CommandValidator`.

        Returns ``(is_safe, reason)``.  The result is recorded in the audit
        log.
        """
        is_safe, reason = self._validator.validate(command)
        self._audit("command_check", {"command": command, "is_safe": is_safe, "reason": reason})
        return is_safe, reason

    async def request_tool_approval(
        self,
        tool_name: str,
        params: dict[str, Any],
        reason: str,
    ) -> bool:
        """Request approval for a tool execution.

        Delegates to the :class:`ApprovalManager`.  The request and outcome
        are recorded in the audit log.
        """
        approved = await self._approval.request_approval(tool_name, params, reason)
        self._audit("tool_approval", {
            "tool_name": tool_name,
            "params": params,
            "reason": reason,
            "approved": approved,
            "mode": self._approval._mode.value,
        })
        return approved

    async def execute_sandboxed(
        self,
        code_or_cmd: str,
        exec_type: str = "python",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute code or a shell command in the sandbox.

        Args:
            code_or_cmd: Python source code or a shell command string.
            exec_type: ``"python"`` or ``"shell"``.
            timeout: Override the configured default timeout.

        Returns:
            The result dict from the underlying sandbox executor.
        """
        self._audit("sandbox_execute", {
            "exec_type": exec_type,
            "code_preview": code_or_cmd[:200],
        })

        if exec_type == "python":
            result = await self._sandbox.execute_python(code_or_cmd, timeout=timeout)
        elif exec_type == "shell":
            result = await self._sandbox.execute_shell(code_or_cmd, timeout=timeout)
        else:
            result = {
                "exit_code": -4,
                "stdout": "",
                "stderr": f"Unknown execution type: {exec_type!r}",
                "timed_out": False,
                "duration": 0.0,
            }

        return result

    def get_status(self) -> dict[str, Any]:
        """Return a comprehensive status snapshot of the security subsystem.

        Includes validator state, approval mode and pending count, sandbox
        stats, and a summary of recent audit entries.
        """
        return {
            "validator": {
                "whitelist_count": len(self._validator.whitelist_patterns),
                "blacklist_count": len(self._validator.blacklist_patterns),
            },
            "approval": {
                "mode": self._approval._mode.value,
                "pending_count": len(self._approval.list_pending()),
                "approved_cache_size": len(self._approval._approved_commands),
                "denied_cache_size": len(self._approval._denied_commands),
            },
            "sandbox": self._sandbox.get_stats(),
            "audit": {
                "total_entries": len(self._audit_log),
                "max_entries": self._max_audit_entries,
                "recent": self._audit_log[-5:],
            },
        }

    # -- Component accessors ----------------------------------------------

    @property
    def validator(self) -> CommandValidator:
        """Direct access to the underlying :class:`CommandValidator`."""
        return self._validator

    @property
    def approval_manager(self) -> ApprovalManager:
        """Direct access to the underlying :class:`ApprovalManager`."""
        return self._approval

    @property
    def sandbox(self) -> Sandbox:
        """Direct access to the underlying :class:`Sandbox`."""
        return self._sandbox

    # -- Audit helpers ----------------------------------------------------

    def _audit(self, event_type: str, data: dict[str, Any]) -> None:
        """Append an entry to the in-memory audit log."""
        entry: dict[str, Any] = {
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **data,
        }
        self._audit_log.append(entry)
        # Trim to ring-buffer size
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]


# ======================================================================
# Utility helpers
# ======================================================================


def sys_executable() -> str:
    """Return the current Python executable path."""
    import sys as _sys
    return _sys.executable


def json_dumps_safe(obj: Any) -> str:
    """Serialise *obj* to JSON, replacing non-serialisable values."""
    import json as _json

    def _default(o: Any) -> Any:
        return f"<{type(o).__name__}>"

    return _json.dumps(obj, default=_default, sort_keys=True)


def _empty_config():
    """Return a minimal namespace-like object with no security attributes."""
    return type("EmptyConfig", (), {})()


# ======================================================================
# Convenience: audit summary logger
# ======================================================================


def log_security_summary(manager: SecurityManager) -> None:
    """Log a human-readable summary of the security manager's state."""
    status = manager.get_status()
    logger.info("=== Security Summary ===")
    logger.info(
        "Validator: %d whitelist, %d blacklist patterns",
        status["validator"]["whitelist_count"],
        status["validator"]["blacklist_count"],
    )
    logger.info(
        "Approval: mode=%s, %d pending",
        status["approval"]["mode"],
        status["approval"]["pending_count"],
    )
    logger.info(
        "Sandbox: %d executions, %.3fs total",
        status["sandbox"]["execution_count"],
        status["sandbox"]["total_duration"],
    )
    logger.info(
        "Audit: %d / %d entries",
        status["audit"]["total_entries"],
        status["audit"]["max_entries"],
    )
