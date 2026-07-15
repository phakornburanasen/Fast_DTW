# tests/test_file_writer.py — Unit tests for FileWriter
# Output format: UTF-16 LE with BOM + CRLF (matches Excel tab-delimited export)
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from file_writer import FileWriter


class TestFileWriter:
    def test_tab_delimited_format(self, tmp_path):
        writer = FileWriter(str(tmp_path))
        rows = [["col1", "col2", "col3"], ["a", "b", "c"]]
        writer.write_tab_file("test.txt", rows)

        content = (tmp_path / "test.txt").read_text(encoding="utf-16")
        lines = content.splitlines()
        assert lines[0] == "col1\tcol2\tcol3"
        assert lines[1] == "a\tb\tc"

    def test_crlf_line_endings(self, tmp_path):
        """DTW on Windows expects CRLF (\\r\\n) line endings."""
        writer = FileWriter(str(tmp_path))
        rows = [["x", "y"], ["1", "2"]]
        writer.write_tab_file("test.txt", rows)

        content = (tmp_path / "test.txt").read_bytes().decode("utf-16")
        assert "\r\n" in content, "File should use CRLF line endings"
        lines = content.splitlines()
        assert len(lines) == len(rows)

    def test_utf16_encoding_with_thai_text(self, tmp_path):
        """Thai characters must survive the UTF-16 round-trip."""
        writer = FileWriter(str(tmp_path))
        thai = "Transfer for ใบเกลี่ยโอน"
        rows = [["JournalMemo"], [thai]]
        writer.write_tab_file("test.txt", rows)

        content = (tmp_path / "test.txt").read_text(encoding="utf-16")
        assert thai in content

    def test_bom_present(self, tmp_path):
        """File must start with UTF-16 BOM so Excel/DTW recognises the encoding."""
        writer = FileWriter(str(tmp_path))
        writer.write_tab_file("test.txt", [["h"], ["v"]])
        raw = (tmp_path / "test.txt").read_bytes()
        assert raw[:2] in (b"\xff\xfe", b"\xfe\xff"), "Missing UTF-16 BOM"

    def test_directory_auto_creation(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()
        FileWriter(str(nested)).write_tab_file("test.txt", [["h"], ["v"]])
        assert nested.exists()
        assert (nested / "test.txt").exists()

    def test_overwrite_existing_file(self, tmp_path):
        writer = FileWriter(str(tmp_path))
        writer.write_tab_file("test.txt", [["old"], ["data"]])
        writer.write_tab_file("test.txt", [["new"], ["content"]])

        content = (tmp_path / "test.txt").read_text(encoding="utf-16")
        assert "old" not in content
        assert "new" in content

    def test_returns_absolute_path(self, tmp_path):
        writer = FileWriter(str(tmp_path))
        result = writer.write_tab_file("out.txt", [["h"], ["v"]])
        assert os.path.isabs(result)
        assert result.endswith("out.txt")
        assert os.path.exists(result)

    def test_existing_directory_does_not_raise(self, tmp_path):
        writer = FileWriter(str(tmp_path))
        writer.write_tab_file("a.txt", [["h"], ["v"]])
        writer.write_tab_file("b.txt", [["h"], ["v"]])  # should not raise
