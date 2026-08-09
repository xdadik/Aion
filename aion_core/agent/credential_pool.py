"""
Credential pool with multi-credential failover.

Manages a pool of API credentials from multiple sources with automatic
rotation, rate-limit tracking, expiry handling, and thread-safe access.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# SECURITY: redactor for safe serialization - prevents API keys from
# appearing in to_dict() output, error messages, or log files.
try:
    from aion_core.security.redact import redactor as _redactor
except ImportError:
    _redactor = None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CredentialSource(str, Enum):
    """Origin of a credential."""

    ENV_VAR = "env_var"
    DOTENV = "dotenv"
    CONFIG_FILE = "config_file"
    CLI_TOOL = "cli_tool"
    OAUTH = "oauth"
    DEVICE_CODE = "device_code"
    CUSTOM = "custom"


class RotationStrategy(str, Enum):
    """Strategy for selecting the next credential."""

    ROUND_ROBIN = "round_robin"
    OLDEST_FIRST = "oldest_first"
    RANDOM = "random"
    PRIORITY = "priority"
    LRU = "lru"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PooledCredential:
    """A single credential entry in the pool."""

    id: str
    provider: str
    api_key: str
    source: CredentialSource = CredentialSource.CUSTOM
    expires_at: str | None = None
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal bookkeeping (not persisted)
    _last_used: float = field(default=0.0, repr=False)
    _exhausted: bool = field(default=False, repr=False)
    _rate_limited_until: float = field(default=0.0, repr=False)
    _use_count: int = field(default=0, repr=False)

    # -- helpers ----------------------------------------------------------

    def is_expired(self) -> bool:
        """Return True when the credential has passed its expiry date."""
        if self.expires_at is None:
            return False
        try:
            if isinstance(self.expires_at, datetime):
                expiry = self.expires_at
            else:
                expiry = datetime.fromisoformat(self.expires_at)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            return datetime.now(UTC) >= expiry
        except (ValueError, TypeError):
            return False

    def is_available(self, now: float | None = None) -> bool:
        """Credential is usable when not exhausted, not expired, and not
        currently rate-limited."""
        if self._exhausted:
            return False
        if self.is_expired():
            return False
        ts = now if now is not None else time.time()
        return not ts < self._rate_limited_until

    def to_dict(self) -> dict[str, Any]:
        """Serializable dictionary (excludes private fields)."""
        expires = None
        if self.expires_at is not None:
            if isinstance(self.expires_at, datetime):
                expires = self.expires_at.isoformat()
            else:
                expires = str(self.expires_at)
        return {
            "id": self.id,
            "provider": self.provider,
            "api_key": "***REDACTED***",
            "source": (
                self.source.value
                if isinstance(self.source, CredentialSource)
                else str(self.source)
            ),
            "expires_at": expires,
            "priority": self.priority,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PooledCredential:
        """Reconstruct from a serialised dictionary."""
        source = data.get("source", "custom")
        if isinstance(source, str):
            source = CredentialSource(source)
        return cls(
            id=data["id"],
            provider=data["provider"],
            # SECURITY: from_dict is only used with trusted input files
            # that were created by save_to_file (which redacts keys).
            # If loading from untrusted sources, add validation here.
            api_key=data["api_key"],
            source=source,
            expires_at=data.get("expires_at"),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# CredentialPool
# ---------------------------------------------------------------------------


class CredentialPool:
    """Thread-safe pool of PooledCredential objects with rotation
    strategies and automatic failover.

    Parameters
    ----------
    strategy:
        Default rotation strategy (can be overridden per rotate call).
    rate_limit_cooldown:
        Seconds to suspend a credential after it is marked rate-limited.
    """

    def __init__(
        self,
        strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
        rate_limit_cooldown: float = 60.0,
    ) -> None:
        self._strategy = strategy
        self._rate_limit_cooldown = rate_limit_cooldown
        self._credentials: dict[str, PooledCredential] = {}
        self._provider_index: dict[str, int] = {}
        self._lock = threading.RLock()
        self._stats: dict[str, int] = {
            "total_rotations": 0,
            "total_exhausted": 0,
            "total_rate_limited": 0,
            "total_expired_cleaned": 0,
        }

    # -- loading -----------------------------------------------------------

    def load_from_env(
        self,
        env_mapping: dict[str, str] | None = None,
    ) -> int:
        """Load credentials from environment variables.

        *env_mapping* maps provider_name to the environment variable that
        holds its API key.  If None, a built-in default mapping is used.

        Returns the number of credentials loaded.
        """
        if env_mapping is None:
            env_mapping = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "google": "GOOGLE_API_KEY",
                "azure": "AZURE_OPENAI_API_KEY",
            }
        count = 0
        with self._lock:
            for provider, var_name in env_mapping.items():
                key = os.environ.get(var_name)
                if not key:
                    continue
                cred = PooledCredential(
                    id=f"env_{provider}_{var_name}",
                    provider=provider,
                    api_key=key,
                    source=CredentialSource.ENV_VAR,
                    priority=10,
                )
                self._credentials[cred.id] = cred
                count += 1
                # SECURITY: never log the actual key value
                logger.debug(
                    "Loaded credential for %s from env var %s (redacted)",
                    provider,
                    var_name,
                )
        return count

    def load_from_file(self, path: str | Path) -> int:
        """Load credentials from a JSON file.

        Expected format is a JSON array of credential objects matching
        the PooledCredential.to_dict schema.

        Returns the number of credentials loaded.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Credential file not found: {path}")
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            raise ValueError("Credential file must contain a JSON array")
        count = 0
        with self._lock:
            for entry in raw:
                cred = PooledCredential.from_dict(entry)
                self._credentials[cred.id] = cred
                count += 1
        logger.info("Loaded %d credential(s) from %s", count, path)
        return count

    # -- mutation ----------------------------------------------------------

    def add_credential(self, credential: PooledCredential) -> None:
        """Add or replace a credential in the pool."""
        with self._lock:
            self._credentials[credential.id] = credential
            # SECURITY: log only the credential ID and provider, never the key
            logger.debug(
                "Added credential %s for provider %s",
                credential.id,
                credential.provider,
            )

    def remove_credential(self, credential_id: str) -> bool:
        """Remove a credential by its id.  Returns True if found."""
        with self._lock:
            removed = self._credentials.pop(credential_id, None) is not None
            if removed:
                logger.debug("Removed credential %s", credential_id)
            return removed

    # -- rotation / selection ---------------------------------------------

    def rotate(
        self,
        provider: str,
        strategy: RotationStrategy | None = None,
    ) -> PooledCredential | None:
        """Return the next available credential for *provider*.

        Uses *strategy* if given, otherwise the pool default.  Returns
        None when no credential is available.
        """
        strat = strategy or self._strategy
        with self._lock:
            candidates = [
                c
                for c in self._credentials.values()
                if c.provider == provider and c.is_available()
            ]
            if not candidates:
                logger.warning("No available credentials for provider %s", provider)
                return None

            selected: PooledCredential
            if strat == RotationStrategy.ROUND_ROBIN:
                idx = self._provider_index.get(provider, 0)
                selected = candidates[idx % len(candidates)]
                self._provider_index[provider] = (idx + 1) % len(candidates)
            elif strat == RotationStrategy.OLDEST_FIRST:
                selected = min(candidates, key=lambda c: c._last_used)
            elif strat == RotationStrategy.RANDOM:
                selected = random.choice(candidates)
            elif strat == RotationStrategy.PRIORITY:
                selected = max(candidates, key=lambda c: (c.priority, -c._last_used))
            elif strat == RotationStrategy.LRU:
                selected = min(candidates, key=lambda c: c._last_used)
            else:
                selected = candidates[0]

            selected._last_used = time.time()
            selected._use_count += 1
            self._stats["total_rotations"] += 1
            return selected

    def get_active(self, provider: str) -> PooledCredential | None:
        """Convenience: return the current active credential for *provider*."""
        return self.rotate(provider)

    # -- marking -----------------------------------------------------------

    def mark_exhausted(self, credential_id: str) -> bool:
        """Mark a credential as exhausted (e.g. quota depleted)."""
        with self._lock:
            cred = self._credentials.get(credential_id)
            if cred is None:
                return False
            cred._exhausted = True
            self._stats["total_exhausted"] += 1
            logger.info("Credential %s marked as exhausted", credential_id)
            return True

    def mark_rate_limited(
        self, credential_id: str, cooldown: float | None = None
    ) -> bool:
        """Mark a credential as rate-limited for *cooldown* seconds."""
        cd = cooldown if cooldown is not None else self._rate_limit_cooldown
        with self._lock:
            cred = self._credentials.get(credential_id)
            if cred is None:
                return False
            cred._rate_limited_until = time.time() + cd
            self._stats["total_rate_limited"] += 1
            logger.info("Credential %s rate-limited for %.1fs", credential_id, cd)
            return True

    # -- queries -----------------------------------------------------------

    def get_all(self, provider: str | None = None) -> list[PooledCredential]:
        """Return all credentials, optionally filtered by *provider*."""
        with self._lock:
            creds = list(self._credentials.values())
        if provider is not None:
            creds = [c for c in creds if c.provider == provider]
        return creds

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the pool."""
        with self._lock:
            creds = list(self._credentials.values())
        now = time.time()
        return {
            **self._stats,
            "total_credentials": len(creds),
            "available": sum(1 for c in creds if c.is_available(now)),
            "exhausted": sum(1 for c in creds if c._exhausted),
            "rate_limited": sum(1 for c in creds if now < c._rate_limited_until),
            "expired": sum(1 for c in creds if c.is_expired()),
            "providers": sorted({c.provider for c in creds}),
            "strategy": self._strategy.value,
        }

    # -- persistence -------------------------------------------------------

    def save_to_file(self, path: str | Path) -> None:
        """Persist all credentials to a JSON file.

        Note: internal runtime state (exhausted, rate-limited, use count)
        is not persisted.
        """
        path = Path(path)
        with self._lock:
            data = [c.to_dict() for c in self._credentials.values()]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        # SECURITY: file path is safe to log; file contents contain
        # redacted keys (see to_dict). Ensure the file has restricted perms.
        logger.info("Saved %d credential(s) to %s", len(data), path)
        # SECURITY: restrict file permissions to owner-only (0600)
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.warning("Failed to set restrictive permissions on %s", path)

    # -- housekeeping ------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Remove all expired credentials.  Returns count removed."""
        removed_ids: list[str] = []
        with self._lock:
            for cid, cred in list(self._credentials.items()):
                if cred.is_expired():
                    removed_ids.append(cid)
            for cid in removed_ids:
                del self._credentials[cid]
            self._stats["total_expired_cleaned"] += len(removed_ids)
        if removed_ids:
            logger.info("Cleaned up %d expired credential(s)", len(removed_ids))
        return len(removed_ids)

    # -- dunder ------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._credentials)

    def __repr__(self) -> str:
        return (
            f"CredentialPool(strategy={self._strategy.value!r}, "
            f"credentials={len(self)})"
        )
