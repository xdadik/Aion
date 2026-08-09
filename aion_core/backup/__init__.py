"""Aion Hand Backup & Restore.

Full backup of agent state to a single tar.gz archive:
    - memories (MEMORY.md, USER.md, *.db, *.json)
    - skills (skill_*.json files)
    - personas (~/.aion-hand/personas/*.md)
    - config (~/.aion-hand/config.json)
    - conversation history
    - lessons (runtime learning state)

Restore unpacks an archive back into ~/.aion-hand/.

Usage:
    from aion_core.backup import BackupManager
    bm = BackupManager()
    archive = await bm.backup()               # → ~/.aion-hand/backups/aion-2026-08-08.tar.gz
    await bm.restore(archive)                 # restore from archive
    archives = bm.list_backups()              # list all backups
    bm.cleanup_old(keep=10)                   # delete old, keep newest 10
"""

from __future__ import annotations

import asyncio
import os
import tarfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger("aion_hand.backup")


# ---------------------------------------------------------------------------
# Backup entry
# ---------------------------------------------------------------------------


@dataclass
class BackupEntry:
    """A single backup archive on disk."""

    path: Path
    created_at: float  # unix timestamp
    size_bytes: int

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "created_at": datetime.fromtimestamp(self.created_at, UTC).isoformat(),
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_mb, 2),
            "age_days": round(self.age_days, 1),
        }


# ---------------------------------------------------------------------------
# Backup manager
# ---------------------------------------------------------------------------


class BackupManager:
    """Back up and restore the entire ~/.aion-hand/ directory."""

    def __init__(
        self,
        home_dir: Path | str | None = None,
        backup_dir: Path | str | None = None,
    ) -> None:
        self.home_dir = Path(home_dir) if home_dir else Path.home() / ".aion-hand"
        self.backup_dir = Path(backup_dir) if backup_dir else self.home_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    #  Backup
    # ------------------------------------------------------------------

    async def backup(
        self,
        *,
        label: str | None = None,
        compress: bool = True,
        include_voice: bool = False,
    ) -> Path:
        """Create a backup archive. Returns the path to the .tar.gz file."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
        suffix = f"-{label}" if label else ""
        archive_name = f"aion-{timestamp}{suffix}.tar.gz"
        archive_path = self.backup_dir / archive_name

        # Run the (blocking) tar operation in an executor
        await asyncio.get_event_loop().run_in_executor(
            None,
            self._create_archive_sync,
            archive_path,
            compress,
            include_voice,
        )

        size = archive_path.stat().st_size
        logger.info(f"Backup created: {archive_path} ({size / 1024:.1f} KB)")
        return archive_path

    def _create_archive_sync(
        self, archive_path: Path, compress: bool, include_voice: bool
    ) -> None:
        """Synchronous tar archive creation."""
        if not self.home_dir.is_dir():
            raise FileNotFoundError(f"Home directory does not exist: {self.home_dir}")

        # Items to back up (relative paths inside ~/.aion-hand/)
        items_to_include: list[str] = []
        for item in [
            "config.json",
            "mcp_servers.json",
            "memories",
            "skills",
            "personas",
            "cron_jobs.json",
            "lessons.json",
            "conversation.md",
        ]:
            p = self.home_dir / item
            if p.exists():
                items_to_include.append(item)

        # Voice files can be large — opt-in
        if include_voice and (self.home_dir / "voice").is_dir():
            items_to_include.append("voice")

        # Never include the backups dir itself (recursive growth)
        # Never include caches

        # Build manifest first
        import json

        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "aion_version": self._detect_version(),
            "items": items_to_include,
            "compress": compress,
            "host": os.uname().nodename if hasattr(os, "uname") else "unknown",
        }
        manifest_str = json.dumps(manifest, indent=2)

        mode = "w:gz" if compress else "w"
        with tarfile.open(archive_path, mode) as tar:
            for item in items_to_include:
                full = self.home_dir / item
                try:
                    tar.add(full, arcname=item, recursive=True)
                except (OSError, PermissionError) as exc:
                    logger.warning(f"Could not add {item} to backup: {exc}")

            # Add manifest as an in-archive file
            import io

            manifest_bytes = manifest_str.encode("utf-8")
            info = tarfile.TarInfo(name="MANIFEST.json")
            info.size = len(manifest_bytes)
            info.mtime = time.time()
            tar.addfile(info, io.BytesIO(manifest_bytes))

    def _detect_version(self) -> str:
        try:
            from aion_core import __version__  # type: ignore[attr-defined]

            return __version__
        except Exception:  # noqa: BLE001
            return "unknown"

    # ------------------------------------------------------------------
    #  Restore
    # ------------------------------------------------------------------

    async def restore(
        self, archive_path: Path | str, *, overwrite: bool = False
    ) -> dict[str, Any]:
        """Restore from a backup archive.

        Args:
            archive_path: Path to the .tar.gz file.
            overwrite: If True, overwrite existing files. If False, skip them.

        Returns:
            Dict with 'extracted' (list of paths) and 'skipped' (list of paths).
        """
        archive_path = Path(archive_path)
        if not archive_path.is_file():
            raise FileNotFoundError(f"Backup archive not found: {archive_path}")

        self.home_dir.mkdir(parents=True, exist_ok=True)

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self._extract_archive_sync,
            archive_path,
            overwrite,
        )
        logger.info(f"Restored {len(result['extracted'])} items from {archive_path}")
        return result

    def _extract_archive_sync(
        self, archive_path: Path, overwrite: bool
    ) -> dict[str, Any]:
        """Synchronous tar extraction."""
        extracted: list[str] = []
        skipped: list[str] = []
        with tarfile.open(archive_path, "r:*") as tar:
            for member in tar.getmembers():
                target = self.home_dir / member.name
                # Safety: prevent path traversal outside home_dir
                try:
                    target_resolved = target.resolve()
                    home_resolved = self.home_dir.resolve()
                    # Use is_relative_to when available (Python 3.9+), fallback to startswith check
                    try:
                        is_inside = target_resolved.is_relative_to(home_resolved)
                    except AttributeError:
                        is_inside = (
                            str(target_resolved).startswith(str(home_resolved) + "/")
                            or target_resolved == home_resolved
                        )
                    if not is_inside:
                        skipped.append(f"{member.name} (path traversal blocked)")
                        continue
                except (OSError, RuntimeError):
                    skipped.append(f"{member.name} (resolve failed)")
                    continue

                if target.exists() and not overwrite:
                    skipped.append(member.name)
                    continue
                try:
                    # Use the modern 'data' filter (Python 3.12+) to prevent
                    # path-traversal and other tar-based attacks.
                    try:
                        tar.extract(
                            member, path=self.home_dir, filter="data"
                        )  # noqa: S202
                    except TypeError:
                        # Older Python without filter kwarg
                        tar.extract(member, path=self.home_dir)  # noqa: S202
                    extracted.append(member.name)
                except (OSError, PermissionError) as exc:
                    skipped.append(f"{member.name} ({exc})")
        return {"extracted": extracted, "skipped": skipped}

    # ------------------------------------------------------------------
    #  List & cleanup
    # ------------------------------------------------------------------

    def list_backups(self) -> list[BackupEntry]:
        """List all backup archives, newest first."""
        entries: list[BackupEntry] = []
        for p in self.backup_dir.glob("aion-*.tar.gz"):
            try:
                stat = p.stat()
                entries.append(
                    BackupEntry(
                        path=p,
                        created_at=stat.st_mtime,
                        size_bytes=stat.st_size,
                    )
                )
            except OSError:
                continue
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries

    def cleanup_old(self, keep: int = 10) -> int:
        """Delete old backups, keeping only the newest `keep` archives.

        Returns the number of archives deleted.
        """
        entries = self.list_backups()
        if len(entries) <= keep:
            return 0
        to_delete = entries[keep:]
        deleted = 0
        for entry in to_delete:
            try:
                entry.path.unlink()
                deleted += 1
            except OSError as exc:
                logger.warning(f"Could not delete {entry.path}: {exc}")
        logger.info(f"Deleted {deleted} old backups (kept {keep})")
        return deleted

    # ------------------------------------------------------------------
    #  Manifest inspection
    # ------------------------------------------------------------------

    def read_manifest(self, archive_path: Path | str) -> dict[str, Any] | None:
        """Read the MANIFEST.json from a backup archive (without extracting)."""
        archive_path = Path(archive_path)
        if not archive_path.is_file():
            return None
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                try:
                    f = tar.extractfile("MANIFEST.json")
                    if f is None:
                        return None
                    import json

                    return json.loads(f.read().decode("utf-8"))
                except KeyError:
                    return None
        except (tarfile.TarError, OSError) as exc:
            logger.error(f"Could not read manifest: {exc}")
            return None


__all__ = ["BackupManager", "BackupEntry"]
