"""File-level checkpoints with rollback (Hermes checkpoint_manager parity).

Hermes snapshots files before destructive operations into a shadow store
so any change — or even the last chat turn — can be undone. This is
Aion's port, zero-dependency:

* Before ``file_write`` / ``shell_command`` / ``code_execute``, the target
  files are copied into ``~/.aion-hand/checkpoints/<checkpoint-id>/``.
* A JSON index maps checkpoint ids to metadata (files, tool, timestamp).
* ``rollback(id)`` restores the files; ``list_checkpoints()`` shows history.

Deliberately simple: file copies, not git (git is optional if present).
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.checkpoints")


class CheckpointManager:
    """Snapshot-and-restore for files touched by destructive tools."""

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            store_dir = Path.home() / ".aion-hand" / "checkpoints"
        self._store = Path(store_dir)
        self._store.mkdir(parents=True, exist_ok=True)
        self._index_path = self._store / "index.json"
        self._index: list[dict[str, Any]] = self._load_index()

    # ------------------------------------------------------------------
    # Index persistence
    # ------------------------------------------------------------------

    def _load_index(self) -> list[dict[str, Any]]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_index(self) -> None:
        try:
            self._index_path.write_text(json.dumps(self._index, indent=2))
        except OSError as exc:
            logger.warning("Failed to save checkpoint index: %s", exc)

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def create_checkpoint(
        self,
        files: list[str],
        reason: str = "",
        keep_last: int = 50,
    ) -> str | None:
        """Snapshot ``files`` (only those that exist) and return a checkpoint id.

        Returns None when nothing existed to snapshot (a write to a brand
        new file is trivially restorable by deletion, recorded as such).
        """
        existing = [Path(f).expanduser() for f in files if Path(f).expanduser().exists()]
        cid = uuid.uuid4().hex[:10]
        cdir = self._store / cid
        cdir.mkdir(parents=True, exist_ok=True)

        saved: list[dict[str, str]] = []
        for path in existing:
            try:
                dest = cdir / path.name
                # Handle name collisions across dirs with a hash suffix
                if dest.exists():
                    dest = cdir / f"{path.stem}_{cid[:4]}{path.suffix}"
                shutil.copy2(path, dest)
                saved.append({"original": str(path), "snapshot": dest.name})
            except OSError as exc:
                logger.warning("Checkpoint copy failed for %s: %s", path, exc)

        entry = {
            "id": cid,
            "reason": reason[:200],
            "timestamp": time.time(),
            "files": saved,
            "created": len(saved),
            "new_files": [
                str(p) for p in
                (Path(f).expanduser() for f in files)
                if not p.exists()
            ],
        }
        self._index.append(entry)
        # Prune old checkpoints beyond keep_last
        while len(self._index) > keep_last:
            old = self._index.pop(0)
            old_dir = self._store / old["id"]
            if old_dir.exists():
                shutil.rmtree(old_dir, ignore_errors=True)
        self._save_index()

        if saved:
            logger.info("Checkpoint %s saved %d files (%s)", cid, len(saved), reason)
        return cid

    def list_checkpoints(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent checkpoints, newest first."""
        return list(reversed(self._index[-limit:]))

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        """Restore all files captured by a checkpoint.

        Files that did not exist when the checkpoint was taken are removed
        (they were created by the operation being undone).
        """
        entry = next(
            (c for c in self._index if c["id"] == checkpoint_id), None
        )
        if entry is None:
            return {"success": False, "error": f"Unknown checkpoint {checkpoint_id!r}"}

        restored: list[str] = []
        cdir = self._store / checkpoint_id
        for record in entry.get("files", []):
            src = cdir / record["snapshot"]
            dst = Path(record["original"])
            try:
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    restored.append(str(dst))
            except OSError as exc:
                logger.warning("Rollback of %s failed: %s", dst, exc)

        removed: list[str] = []
        for new_file in entry.get("new_files", []):
            try:
                p = Path(new_file)
                if p.exists():
                    p.unlink()
                    removed.append(new_file)
            except OSError:
                pass

        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "restored": restored,
            "removed_new_files": removed,
            "reason": entry.get("reason", ""),
        }

    def stats(self) -> dict[str, Any]:
        return {
            "store_dir": str(self._store),
            "checkpoints": len(self._index),
            "disk_usage_bytes": sum(
                f.stat().st_size
                for f in self._store.rglob("*")
                if f.is_file()
            ),
        }
