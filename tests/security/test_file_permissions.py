"""Tests for secure file creation helpers (Section 4)."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

# Windows has no POSIX permission bits: os.chmod there only toggles the
# read-only flag, so directories always report 0o777 and files 0o666 no
# matter what mode is requested. These tests assert the POSIX guarantee,
# so they are meaningful only on POSIX. Note the underlying limitation is
# real, not cosmetic -- on Windows these files genuinely are not
# restricted to the owner, and ACLs would be needed to get an equivalent.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits are not supported on Windows (chmod only toggles read-only)",
)


class TestSecureMkdir:
    """secure_mkdir should create directories with 0o700."""

    @posix_only
    def test_creates_directory_with_700(self) -> None:
        from orion.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_dir"
            result = secure_mkdir(target)
            assert result.is_dir()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700

    def test_creates_parent_directories(self) -> None:
        from orion.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "c"
            result = secure_mkdir(target)
            assert result.is_dir()

    @posix_only
    def test_existing_directory_gets_permission_fix(self) -> None:
        from orion.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir(mode=0o755)
            secure_mkdir(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700


class TestSecureCreate:
    """secure_create should create files with 0o600."""

    @posix_only
    def test_creates_file_with_600(self) -> None:
        from orion.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_file.db"
            result = secure_create(target)
            assert result.exists()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    @posix_only
    def test_existing_file_gets_permission_fix(self) -> None:
        from orion.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.db"
            target.write_text("data")
            os.chmod(target, 0o644)
            secure_create(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    @posix_only
    def test_creates_parent_directory_with_700(self) -> None:
        from orion.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "file.db"
            secure_create(target)
            parent_mode = stat.S_IMODE(os.stat(target.parent).st_mode)
            assert parent_mode == 0o700
