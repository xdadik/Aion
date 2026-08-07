from pathlib import Path

import pytest

from aion_core.security.secure_sandbox import (
    SecurityPolicyError,
    resolve_workspace_path,
    validate_python_source,
)


def test_python_import_allowlist_blocks_os():
    with pytest.raises(SecurityPolicyError, match="Python import blocked: os"):
        validate_python_source("import os")


def test_python_import_allowlist_allows_math():
    validate_python_source("import math\nprint(math.sqrt(16))")


def test_relative_imports_are_blocked():
    with pytest.raises(SecurityPolicyError, match="Relative Python imports"):
        validate_python_source("from . import thing")


def test_workspace_path_cannot_escape(tmp_path: Path):
    with pytest.raises(SecurityPolicyError, match="escapes workspace"):
        resolve_workspace_path(tmp_path, "../../etc/passwd")


def test_workspace_path_allows_child(tmp_path: Path):
    result = resolve_workspace_path(tmp_path, "project/file.txt")
    assert result == (tmp_path / "project/file.txt").resolve()
