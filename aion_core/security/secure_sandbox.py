"""Hardened execution policy primitives for Aion Hand.

This module provides conservative building blocks for agent-controlled
execution. It does not claim to be a kernel/container sandbox: truly
untrusted code must run in an OS/container sandbox with dropped privileges.

The primitives here enforce three important boundaries before that layer:
1. Python imports are explicit-allowlist based (not denylist based).
2. Shell metacharacters cannot be interpreted because commands use argv.
3. File paths are constrained to an explicit workspace root.
"""
from __future__ import annotations

import ast
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class SecurityPolicyError(ValueError):
    """Raised when requested execution violates the security policy."""


DEFAULT_PYTHON_IMPORTS = frozenset({
    "base64", "collections", "datetime", "decimal", "fractions", "functools",
    "hashlib", "hmac", "itertools", "json", "math", "operator", "re",
    "statistics", "string", "textwrap", "unicodedata",
})
DEFAULT_ENV_KEYS = frozenset({"LANG", "LC_ALL", "TZ"})


class PythonImportPolicy(ast.NodeVisitor):
    """Reject imports outside an explicit top-level module allowlist."""

    def __init__(self, allowed: Iterable[str]) -> None:
        self.allowed = frozenset(allowed)

    def _check(self, name: str) -> None:
        top = name.split(".", 1)[0]
        if top not in self.allowed:
            raise SecurityPolicyError(f"Python import blocked: {top}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            raise SecurityPolicyError("Relative Python imports are blocked")
        if node.module:
            self._check(node.module)
        self.generic_visit(node)


def validate_python_source(code: str, allowed_imports: Iterable[str] = DEFAULT_PYTHON_IMPORTS) -> None:
    """Parse source and enforce the import policy before execution."""
    if not code or len(code) > 256_000:
        raise SecurityPolicyError("Python source is empty or exceeds the 256 KiB limit")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SecurityPolicyError(f"Invalid Python source: {exc}") from exc
    PythonImportPolicy(allowed_imports).visit(tree)


def resolve_workspace_path(workspace: Path | str, requested: Path | str) -> Path:
    """Resolve a path and guarantee it remains inside *workspace*."""
    root = Path(workspace).expanduser().resolve(strict=False)
    requested_path = Path(requested)
    candidate = (root / requested_path).resolve(strict=False) if not requested_path.is_absolute() else requested_path.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SecurityPolicyError(f"Path escapes workspace: {requested}") from exc
    return candidate


class SecureSandbox:
    """Conservative process runner for agent-controlled execution."""

    def __init__(
        self,
        workspace: Path | str,
        *,
        timeout: float = 30.0,
        max_output_bytes: int = 1_000_000,
        allowed_python_imports: Iterable[str] = DEFAULT_PYTHON_IMPORTS,
        env_keys: Iterable[str] = DEFAULT_ENV_KEYS,
    ) -> None:
        if timeout <= 0 or timeout > 300:
            raise ValueError("timeout must be between 0 and 300 seconds")
        if max_output_bytes <= 0 or max_output_bytes > 10_000_000:
            raise ValueError("max_output_bytes must be between 1 and 10,000,000")
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.allowed_python_imports = frozenset(allowed_python_imports)
        self.env_keys = frozenset(env_keys)

    def path(self, requested: Path | str) -> Path:
        return resolve_workspace_path(self.workspace, requested)

    def _environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {k: os.environ[k] for k in self.env_keys if k in os.environ}
        env["PATH"] = "/usr/bin:/bin"
        env["PYTHONPATH"] = ""
        env["PYTHONSTARTUP"] = ""
        env["PYTHONINSPECT"] = ""
        if extra:
            for key, value in extra.items():
                if key.startswith("LD_") or key in {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"}:
                    raise SecurityPolicyError(f"Environment variable blocked: {key}")
                env[key] = value
        return env

    async def execute_argv(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        stdin_data: bytes | None = None,
    ) -> dict[str, object]:
        """Execute an argv vector. A shell is never involved."""
        if not argv or any("\x00" in arg for arg in argv):
            raise SecurityPolicyError("Invalid argv")
        workdir = self.path(cwd or ".")
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workdir),
            env=self._environment(env),
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin_data), self.timeout)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            return {"exit_code": -1, "stdout": "", "stderr": "timeout", "timed_out": True}
        return {
            "exit_code": process.returncode,
            "stdout": stdout[: self.max_output_bytes].decode("utf-8", "replace"),
            "stderr": stderr[: self.max_output_bytes].decode("utf-8", "replace"),
            "timed_out": False,
        }

    async def execute_python(self, code: str) -> dict[str, object]:
        """Execute import-policy-checked Python in a separate interpreter.

        For production multi-tenant/untrusted execution, put this process in
        a real container/VM with a read-only image, dropped capabilities,
        seccomp/AppArmor, a non-root UID, CPU/memory limits and no network.
        """
        validate_python_source(code, self.allowed_python_imports)
        runner = (
            "import sys\n"
            "code=sys.stdin.read()\n"
            "exec(compile(code, '<aion-sandbox>', 'exec'), {'__name__':'__main__'})\n"
        )
        return await self.execute_argv(
            [sys.executable, "-I", "-c", runner],
            env={"AION_SANDBOX": "1"},
            stdin_data=code.encode("utf-8"),
        )
