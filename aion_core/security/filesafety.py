"""
Hermes File Safety System
========================
A comprehensive file safety checker that prevents accidental or malicious
modification of sensitive system files, credential stores, and configuration
artefacts.  Designed for cross-platform use (Linux, macOS, Windows) with
symlink-resolution and atomic write support.

Only the Python standard library is used — no third-party dependencies.

Public API
----------
- :class:`RiskLevel`          – Enum for severity classification.
- :class:`FileSafetyResult`    – Dataclass returned by validation methods.
- :class:`FileSafetyChecker`   – Main gatekeeper for file operations.

Typical usage
-------------
>>> checker = FileSafetyChecker()
>>> result = checker.validate_operation("/etc/passwd", "write")
>>> if not result.allowed:
...     print(f"BLOCKED – {result.reason} (risk={result.risk_level.name})")
"""

from __future__ import annotations

import enum
import fnmatch
import os
import platform
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Union

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

_SYSTEM = platform.system().lower()  # 'linux', 'darwin', 'windows'

_IS_WINDOWS = _SYSTEM == "windows"
_IS_POSIX = not _IS_WINDOWS


def _home() -> str:
    """Return the current user's home directory, expanded and normalised."""
    return os.path.realpath(os.path.expanduser("~"))


def _norm(path: str) -> str:
    """Normalise *path* resolving symlinks, user-tildes and dot-segments."""
    return os.path.realpath(os.path.expanduser(path))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RiskLevel(enum.IntEnum):
    """Severity level for a file-safety violation.

    Ordered from least to most dangerous so that ``max(risk_a, risk_b)``
    works as expected.
    """

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileSafetyResult:
    """Immutable result produced by :meth:`FileSafetyChecker.validate_operation`.

    Attributes
    ----------
    allowed : bool
        ``True`` when the requested operation is permitted.
    reason : str
        Human-readable explanation — always populated.
    risk_level : RiskLevel
        Assessed risk if the operation were to proceed.
    """

    allowed: bool
    reason: str
    risk_level: RiskLevel = RiskLevel.NONE

    def __repr__(self) -> str:
        return (
            f"FileSafetyResult(allowed={self.allowed!r}, "
            f"reason={self.reason!r}, "
            f"risk_level={self.risk_level.name})"
        )


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class FileSafetyChecker:
    """Gatekeeper that decides whether read / write operations on filesystem
    paths are safe to proceed.

    The checker maintains two protection tables:

    * **denied paths** — patterns (globs and exact) for which writes are
      always rejected.
    * **protected extensions** — file suffixes that trigger elevated-risk
      warnings even when the parent directory is not explicitly protected.

    The built-in defaults cover common credential stores, SSH/TLS secrets,
    system configuration files, environment-variable files, and container /
    orchestration configuration artefacts.
    """

    # -----------------------------------------------------------------
    # 20+ built-in write-denied glob / exact patterns
    # -----------------------------------------------------------------
    _HOME = _home()

    WRITE_DENIED_PATHS: tuple[str, ...] = (
        # -- SSH --
        os.path.join(_HOME, ".ssh", "*"),
        "/etc/ssh/*",
        # -- AWS --
        os.path.join(_HOME, ".aws", "*"),
        # -- GPG --
        os.path.join(_HOME, ".gnupg", "*"),
        # -- Kubernetes --
        os.path.join(_HOME, ".kube", "config"),
        os.path.join(_HOME, ".kube", "*"),
        # -- Docker --
        os.path.join(_HOME, ".docker", "config.json"),
        os.path.join(_HOME, ".docker", "*"),
        # -- Essential system files (POSIX) --
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/sudoers.d/*",
        "/etc/crontab",
        "/etc/cron.d/*",
        "/etc/cron.daily/*",
        "/etc/cron.hourly/*",
        "/etc/cron.weekly/*",
        "/etc/cron.monthly/*",
        "/etc/fstab",
        "/etc/hosts",
        "/etc/hostname",
        "/etc/resolv.conf",
        "/etc/nsswitch.conf",
        "/etc/environment",
        "/etc/security/*",
        "/etc/pam.d/*",
        "/etc/login.defs",
        "/etc/profile",
        "/etc/profile.d/*",
        "/etc/bashrc",
        "/etc/bash.bashrc",
        "/etc/zshrc",
        "/etc/zsh",
        "/etc/fish",
        "/etc/skel/*",
        "/etc/ssh/sshd_config",
        "/etc/ssh/ssh_config",
        # -- Init systems --
        "/etc/systemd/*",
        "/etc/init.d/*",
        "/etc/init/*",
        "/etc/rc.local",
        "/etc/rc.conf",
        # -- Windows equivalents --
        r"C:\Windows\System32\drivers\etc\hosts",
        r"C:\Windows\System32\config\*",
        r"C:\Windows\System32\GroupPolicy\*",
        r"C:\ProgramData\Microsoft\Windows\Start Menu\*",
    )

    # -- Environment / secrets files (anywhere in the tree) --
    _DOT_ENV_GLOBS: tuple[str, ...] = (
        ".env",
        ".env.*",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        ".env.staging",
        "*.env",
    )

    # -- Sensitive extensions --
    _SENSITIVE_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".p7b",
            ".p7c",
            ".der",
            ".cer",
            ".crt",
            ".csr",
            ".jks",
            ".keystore",
            ".pub",
            ".gpg",
            ".asc",
            ".pgp",
            ".sig",
            ".ssh",
        }
    )

    # -----------------------------------------------------------------
    # Constructor
    # -----------------------------------------------------------------

    def __init__(
        self,
        *,
        extra_denied_paths: Iterable[str] | None = None,
        extra_protected_extensions: Iterable[str] | None = None,
    ) -> None:
        # Mutable working copies of the built-in tuples
        self._denied_paths: list[str] = list(self.WRITE_DENIED_PATHS)
        self._denied_operations: dict[str, set[str]] = {}
        self._protected_extensions: set[str] = set(self._SENSITIVE_EXTENSIONS)

        # Seed the operations map — every built-in denied path blocks write
        for p in self._denied_paths:
            self._denied_operations.setdefault(p, set()).add("write")

        # User extensions
        if extra_protected_extensions:
            for ext in extra_protected_extensions:
                self._protected_extensions.add(ext.lower())

        # User paths
        if extra_denied_paths:
            for p in extra_denied_paths:
                self.add_protected_path(p, {"write"})

    # -----------------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------------

    @staticmethod
    def get_protected_extensions() -> frozenset[str]:
        """Return the *full* set of sensitive file extensions (immutable copy).

        This is a class-level accessor so callers can inspect the defaults
        without instantiating a checker.
        """
        return FileSafetyChecker._SENSITIVE_EXTENSIONS

    def get_protected_paths(self) -> dict[str, set[str]]:
        """Return a *copy* of the current denied-path → operations mapping."""
        return {k: set(v) for k, v in self._denied_operations.items()}

    def add_protected_path(self, path: str, operations: Iterable[str]) -> None:
        """Register *path* (glob or exact) as protected for *operations*.

        Parameters
        ----------
        path : str
            Glob pattern or absolute path.  ``~`` and environment variables
            are expanded automatically.
        operations : iterable of str
            Subset of ``{"read", "write", "delete", "execute"}``.
        """
        expanded = _norm(path)
        ops = {op.lower().strip() for op in operations}
        existing = self._denied_operations.setdefault(expanded, set())
        existing.update(ops)
        if expanded not in self._denied_paths:
            self._denied_paths.append(expanded)

    # -----------------------------------------------------------------
    # Path traversal detection
    # -----------------------------------------------------------------

    @staticmethod
    def has_path_traversal(path: str, base: str) -> bool:
        """Return ``True`` when *path* escapes *base* via ``..`` or symlinks.

        Both *path* and *base* are resolved through :func:`os.path.realpath`
        (symlinks followed) before comparison.

        Parameters
        ----------
        path : str
            Candidate path that may contain traversal sequences.
        base : str
            Intended containment directory.

        Examples
        --------
        >>> FileSafetyChecker.has_path_traversal("/tmp/../../etc/passwd", "/tmp")
        True
        >>> FileSafetyChecker.has_path_traversal("/tmp/sub/file.txt", "/tmp")
        False
        """
        resolved_path = _norm(path)
        resolved_base = _norm(base)
        # Ensure base ends with a separator so /tmpfoo isn't mistaken for /tmp
        if not resolved_base.endswith(os.sep):
            resolved_base += os.sep
        return not resolved_path.startswith(resolved_base)

    # -----------------------------------------------------------------
    # Internal matching helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _is_dot_env(filename: str) -> bool:
        """Return ``True`` if *filename* matches any ``.env*`` glob."""
        base = os.path.basename(filename)
        for pattern in FileSafetyChecker._DOT_ENV_GLOBS:
            if fnmatch.fnmatch(base, pattern):
                return True
        return False

    def _matches_denied(self, resolved: str) -> tuple[str, set[str]] | None:
        """Check *resolved* against every denied pattern.

        Returns ``(pattern, blocked_operations)`` on the first match or
        ``None`` when no pattern matches.
        """
        for pattern, ops in self._denied_operations.items():
            resolved_pattern = _norm(pattern)
            # Exact match
            if resolved == resolved_pattern:
                return pattern, ops
            # Glob match (fnmatch works on the whole path)
            if "*" in resolved_pattern or "?" in resolved_pattern or "[" in resolved_pattern:
                if fnmatch.fnmatch(resolved, resolved_pattern):
                    return pattern, ops
        return None

    def _extension_risk(self, resolved: str) -> RiskLevel:
        """Return elevated risk if the file has a sensitive extension."""
        ext = os.path.splitext(resolved)[1].lower()
        if ext in self._protected_extensions:
            return RiskLevel.HIGH
        return RiskLevel.NONE

    # -----------------------------------------------------------------
    # Public validation API
    # -----------------------------------------------------------------

    def is_write_allowed(self, path: str) -> bool:
        """Quick boolean check — is a **write** to *path* permitted?"""
        return self.validate_operation(path, "write").allowed

    def is_read_allowed(self, path: str) -> bool:
        """Quick boolean check — is a **read** of *path* permitted?

        Currently reads are never blocked by the default ruleset, but
        callers that add read-denied paths via :meth:`add_protected_path`
        will see those honoured here.
        """
        return self.validate_operation(path, "read").allowed

    def validate_operation(
        self, path: str, operation: str = "write"
    ) -> FileSafetyResult:
        """Perform a full safety validation of *operation* on *path*.

        Parameters
        ----------
        path : str
            Filesystem path to evaluate.  Tildes and env-vars are expanded.
        operation : str
            One of ``"read"``, ``"write"``, ``"delete"``, ``"execute"``.

        Returns
        -------
        FileSafetyResult
            Immutable dataclass with the verdict.
        """
        operation = operation.lower().strip()
        if not path:
            return FileSafetyResult(
                allowed=False,
                reason="Empty path provided.",
                risk_level=RiskLevel.HIGH,
            )

        resolved = _norm(path)

        # 1. Dangerous parent / root directories
        dangerous_dirs = (
            "/",
            "/etc",
            "/usr",
            "/bin",
            "/sbin",
            "/var",
            "/boot",
            "/dev",
            "/proc",
            "/sys",
        )
        if _IS_POSIX and resolved in dangerous_dirs:
            return FileSafetyResult(
                allowed=False,
                reason=f"Refusing to operate on critical system directory: {resolved}",
                risk_level=RiskLevel.CRITICAL,
            )

        # 2. Explicit denied-path check
        match = self._matches_denied(resolved)
        if match is not None:
            pattern, blocked_ops = match
            if operation in blocked_ops:
                return FileSafetyResult(
                    allowed=False,
                    reason=(
                        f"Path '{path}' matches denied pattern '{pattern}' "
                        f"for operation '{operation}'."
                    ),
                    risk_level=RiskLevel.CRITICAL,
                )

        # 3. .env / dotfile secrets check
        if operation == "write" and self._is_dot_env(resolved):
            return FileSafetyResult(
                allowed=False,
                reason=(
                    f"Refusing to write to environment / secrets file: {path}"
                ),
                risk_level=RiskLevel.HIGH,
            )

        # 4. Sensitive extension check
        ext_risk = self._extension_risk(resolved)
        if ext_risk != RiskLevel.NONE:
            if operation == "write":
                return FileSafetyResult(
                    allowed=False,
                    reason=(
                        f"Refusing to write to sensitive file "
                        f"(extension '{os.path.splitext(resolved)[1]}'): {path}"
                    ),
                    risk_level=ext_risk,
                )
            # Reads of sensitive extensions are allowed but flagged
            return FileSafetyResult(
                allowed=True,
                reason=(
                    f"Path has sensitive extension "
                    f"'{os.path.splitext(resolved)[1]}' — "
                    f"proceed with caution."
                ),
                risk_level=ext_risk,
            )

        # 5. Writable system paths heuristic (POSIX)
        if _IS_POSIX and operation == "write":
            if resolved.startswith("/etc/") or resolved.startswith("/var/"):
                return FileSafetyResult(
                    allowed=False,
                    reason=(
                        f"Write to system configuration directory blocked: {path}"
                    ),
                    risk_level=RiskLevel.HIGH,
                )

        # 6. Windows system paths
        if _IS_WINDOWS and operation == "write":
            win_root = os.path.realpath(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            if resolved.lower().startswith(win_root.lower()):
                return FileSafetyResult(
                    allowed=False,
                    reason=f"Write to Windows system directory blocked: {path}",
                    risk_level=RiskLevel.HIGH,
                )

        # 7. All checks passed
        return FileSafetyResult(
            allowed=True,
            reason=f"Operation '{operation}' on '{path}' is permitted.",
            risk_level=RiskLevel.NONE,
        )

    # -----------------------------------------------------------------
    # Atomic write helper
    # -----------------------------------------------------------------

    def atomic_write(
        self,
        path: str,
        content: str | bytes,
        *,
        mode: int = 0o644,
        encoding: str = "utf-8",
    ) -> FileSafetyResult:
        """Write *content* to *path* **atomically** (temp + fsync + replace).

        The method first validates the write via :meth:`validate_operation`.
        If denied, no filesystem changes are made and the result is returned
        immediately.

        Atomicity is achieved by:
        1. Writing to a temporary file in the **same directory** as *path*
           (guaranteeing the same filesystem / mount).
        2. Calling ``os.fsync()`` to flush kernel buffers.
        3. Renaming the temp file over the target (an atomic operation on
           POSIX and reasonably safe on modern Windows).
        4. Preserving original file permissions when overwriting, otherwise
           applying *mode*.

        Parameters
        ----------
        path : str
            Destination file path.
        content : str | bytes
            Payload to write.
        mode : int
            File-creation permission bits (octal).  Default ``0o644``.
        encoding : str
            Text encoding used when *content* is a ``str``.  Default ``utf-8``.

        Returns
        -------
        FileSafetyResult
            Outcome of the operation.
        """
        # ---- pre-flight validation ----
        check = self.validate_operation(path, "write")
        if not check.allowed:
            return check

        resolved = _norm(path)
        parent = os.path.dirname(resolved) or "."

        # Ensure parent directory exists
        os.makedirs(parent, exist_ok=True)

        # Preserve existing permissions if the file already exists
        existing_mode: int | None = None
        if os.path.exists(resolved):
            existing_mode = stat.S_IMODE(os.stat(resolved).st_mode)

        # ---- write to temporary file in the same directory ----
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".hermes_atomic_",
                dir=parent,
                suffix=os.path.basename(resolved) + ".tmp",
            )
        except OSError as exc:
            return FileSafetyResult(
                allowed=False,
                reason=f"Failed to create temporary file: {exc}",
                risk_level=RiskLevel.MEDIUM,
            )

        try:
            # Convert str → bytes if needed
            if isinstance(content, str):
                data = content.encode(encoding)
            else:
                data = content

            # Write payload
            os.write(fd, data)

            # Flush to disk (fsync)
            os.fsync(fd)

            # Close the fd before rename (required on Windows)
            os.close(fd)
            fd = -1  # sentinel to avoid double-close

            # Apply permissions
            final_mode = existing_mode if existing_mode is not None else mode
            os.chmod(tmp_path, final_mode)

            # Preserve ownership when possible (POSIX)
            if _IS_POSIX and existing_mode is not None:
                try:
                    st = os.stat(resolved)
                    os.chown(tmp_path, st.st_uid, st.st_gid)
                except OSError:
                    pass  # non-fatal — may lack privilege

            # Atomic rename
            if _IS_POSIX:
                os.replace(tmp_path, resolved)
            else:
                # On Windows, os.replace is atomic for local volumes
                os.replace(tmp_path, resolved)

            return FileSafetyResult(
                allowed=True,
                reason=f"Atomically wrote {len(data)} bytes to {path}.",
                risk_level=RiskLevel.NONE,
            )

        except OSError as exc:
            # Best-effort cleanup of the temp file
            try:
                if fd >= 0:
                    os.close(fd)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

            return FileSafetyResult(
                allowed=False,
                reason=f"Atomic write failed: {exc}",
                risk_level=RiskLevel.HIGH,
            )

    # -----------------------------------------------------------------
    # Convenience: check multiple paths at once
    # -----------------------------------------------------------------

    def validate_paths(
        self, paths: Iterable[str], operation: str = "write"
    ) -> list[FileSafetyResult]:
        """Validate a batch of *paths* for a single *operation*.

        Returns a list of :class:`FileSafetyResult` in the same order as
        *paths*.
        """
        return [self.validate_operation(p, operation) for p in paths]

    def batch_write_allowed(self, paths: Iterable[str]) -> dict[str, bool]:
        """Return ``{path: is_allowed}`` mapping for convenience."""
        return {p: self.is_write_allowed(p) for p in paths}

    # -----------------------------------------------------------------
    # Representation
    # -----------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"FileSafetyChecker("
            f"denied_patterns={len(self._denied_paths)}, "
            f"protected_extensions={len(self._protected_extensions)})"
        )
