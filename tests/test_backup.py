"""Tests for the Backup module."""

from __future__ import annotations

import tarfile
import json
from pathlib import Path

import pytest

from aion_core.backup import BackupManager, BackupEntry


class TestBackupManagerInit:
    """Verify BackupManager constructs."""

    def test_init_creates_backup_dir(self, tmp_path):
        home = tmp_path / "home"
        backup_dir = tmp_path / "backups"
        bm = BackupManager(home_dir=home, backup_dir=backup_dir)
        assert backup_dir.is_dir()
        assert bm.home_dir == home


class TestBackupAndRestore:
    """End-to-end backup and restore."""

    @pytest.mark.asyncio
    async def test_backup_creates_archive(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.json").write_text('{"version": "0.1"}')
        (home / "memories").mkdir()
        (home / "memories" / "MEMORY.md").write_text("# Memory\n\nTest memory")
        (home / "skills").mkdir()
        (home / "skills" / "test.md").write_text("# Test Skill")

        bm = BackupManager(home_dir=home, backup_dir=tmp_path / "backups")
        archive = await bm.backup(label="test")
        assert archive.is_file()
        assert archive.suffix == ".gz"
        # Archive should be a valid tar.gz
        assert tarfile.is_tarfile(archive)

    @pytest.mark.asyncio
    async def test_backup_includes_manifest(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.json").write_text("{}")

        bm = BackupManager(home_dir=home, backup_dir=tmp_path / "backups")
        archive = await bm.backup()
        manifest = bm.read_manifest(archive)
        assert manifest is not None
        assert "created_at" in manifest
        assert "items" in manifest

    @pytest.mark.asyncio
    async def test_restore_roundtrip(self, tmp_path):
        home1 = tmp_path / "home1"
        home1.mkdir()
        (home1 / "config.json").write_text('{"version": "0.1"}')
        (home1 / "memories").mkdir()
        (home1 / "memories" / "MEMORY.md").write_text("# Test memory")

        backup_dir = tmp_path / "backups"
        bm = BackupManager(home_dir=home1, backup_dir=backup_dir)
        archive = await bm.backup()

        # Now restore to a different home
        home2 = tmp_path / "home2"
        bm2 = BackupManager(home_dir=home2, backup_dir=backup_dir)
        result = await bm2.restore(archive, overwrite=True)
        assert len(result["extracted"]) > 0
        assert (home2 / "config.json").is_file()
        assert (home2 / "config.json").read_text() == '{"version": "0.1"}'
        assert (home2 / "memories" / "MEMORY.md").is_file()

    @pytest.mark.asyncio
    async def test_restore_without_overwrite_skips_existing(self, tmp_path):
        home1 = tmp_path / "home1"
        home1.mkdir()
        (home1 / "config.json").write_text('{"v": 1}')
        bm = BackupManager(home_dir=home1, backup_dir=tmp_path / "backups")
        archive = await bm.backup()

        # Restore to a home that already has config.json with different content
        home2 = tmp_path / "home2"
        home2.mkdir()
        (home2 / "config.json").write_text('{"v": 99}')  # existing

        bm2 = BackupManager(home_dir=home2, backup_dir=tmp_path / "backups")
        result = await bm2.restore(archive, overwrite=False)
        # Existing file should NOT be overwritten
        assert (home2 / "config.json").read_text() == '{"v": 99}'

    @pytest.mark.asyncio
    async def test_restore_nonexistent_archive_raises(self, tmp_path):
        bm = BackupManager(home_dir=tmp_path / "home", backup_dir=tmp_path / "backups")
        with pytest.raises(FileNotFoundError):
            await bm.restore(tmp_path / "nope.tar.gz")


class TestBackupListing:
    """list_backups and cleanup_old."""

    @pytest.mark.asyncio
    async def test_list_backups_returns_sorted_newest_first(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.json").write_text("{}")
        bm = BackupManager(home_dir=home, backup_dir=tmp_path / "backups")
        # Create 3 backups
        await bm.backup(label="a")
        await bm.backup(label="b")
        await bm.backup(label="c")
        entries = bm.list_backups()
        assert len(entries) == 3
        # Sorted newest first
        assert entries[0].created_at >= entries[1].created_at >= entries[2].created_at

    @pytest.mark.asyncio
    async def test_cleanup_old_deletes_extras(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.json").write_text("{}")
        bm = BackupManager(home_dir=home, backup_dir=tmp_path / "backups")
        for i in range(5):
            await bm.backup(label=f"b{i}")
        assert len(bm.list_backups()) == 5
        deleted = bm.cleanup_old(keep=2)
        assert deleted == 3
        assert len(bm.list_backups()) == 2


class TestBackupEntry:
    """BackupEntry dataclass."""

    def test_entry_to_dict(self, tmp_path):
        import time
        path = tmp_path / "test.tar.gz"
        path.write_bytes(b"fake")
        entry = BackupEntry(path=path, created_at=time.time(), size_bytes=2048)
        d = entry.to_dict()
        assert d["path"] == str(path)
        assert d["size_bytes"] == 2048
        assert d["size_mb"] == round(2048 / (1024 * 1024), 2)
