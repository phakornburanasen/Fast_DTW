# tests/test_file_manager.py — Unit tests for file_manager
from __future__ import annotations

import os
import time
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from file_manager import backup_tf_files, clear_temp_files


class TestClearTempFiles:
    def test_deletes_existing_tf_files(self, tmp_path):
        (tmp_path / "TF_Head.txt").write_text("data")
        (tmp_path / "TF_Detail.txt").write_text("data")

        deleted = clear_temp_files(str(tmp_path))

        assert not (tmp_path / "TF_Head.txt").exists()
        assert not (tmp_path / "TF_Detail.txt").exists()
        assert len(deleted) == 2

    def test_no_error_when_files_absent(self, tmp_path):
        deleted = clear_temp_files(str(tmp_path))
        assert deleted == []

    def test_returns_paths_of_deleted_files(self, tmp_path):
        (tmp_path / "TF_Head.txt").write_text("x")
        deleted = clear_temp_files(str(tmp_path))
        assert any("TF_Head.txt" in p for p in deleted)

    def test_does_not_delete_other_files(self, tmp_path):
        (tmp_path / "other.txt").write_text("keep me")
        clear_temp_files(str(tmp_path))
        assert (tmp_path / "other.txt").exists()


class TestBackupTfFiles:
    def test_moves_files_to_bak_dir(self, tmp_path):
        (tmp_path / "TF_Head.txt").write_text("head")
        (tmp_path / "TF_Detail.txt").write_text("detail")

        moved = backup_tf_files(str(tmp_path))
        bak_dir = tmp_path / "bak_file"

        assert len(moved) == 2
        assert not (tmp_path / "TF_Head.txt").exists()
        assert not (tmp_path / "TF_Detail.txt").exists()
        assert any("TF_Head.txt" in dst for _, dst in moved)
        assert any("TF_Detail.txt" in dst for _, dst in moved)
        assert all(os.path.exists(dst) for _, dst in moved)

    def test_backup_filename_has_timestamp_prefix(self, tmp_path):
        (tmp_path / "TF_Head.txt").write_text("head")
        moved = backup_tf_files(str(tmp_path))
        _, dst = moved[0]
        basename = os.path.basename(dst)
        # Expect: YYYYMMDD_HHMMSS_TF_Head.txt
        parts = basename.split("_")
        assert len(parts) >= 3
        assert parts[0].isdigit() and len(parts[0]) == 8   # YYYYMMDD
        assert parts[1].isdigit() and len(parts[1]) == 6   # HHMMSS

    def test_creates_bak_dir_if_not_exists(self, tmp_path):
        (tmp_path / "TF_Head.txt").write_text("head")
        bak_dir = tmp_path / "bak_file"
        assert not bak_dir.exists()

        backup_tf_files(str(tmp_path))
        assert bak_dir.exists()

    def test_no_error_when_no_files_to_backup(self, tmp_path):
        moved = backup_tf_files(str(tmp_path))
        assert moved == []

    def test_multiple_backups_dont_overwrite(self, tmp_path):
        """Two backups 1 second apart should produce different filenames."""
        (tmp_path / "TF_Head.txt").write_text("first")
        moved1 = backup_tf_files(str(tmp_path))

        time.sleep(1)

        (tmp_path / "TF_Head.txt").write_text("second")
        moved2 = backup_tf_files(str(tmp_path))

        dst1 = moved1[0][1]
        dst2 = moved2[0][1]
        assert dst1 != dst2
        assert os.path.exists(dst1)
        assert os.path.exists(dst2)
