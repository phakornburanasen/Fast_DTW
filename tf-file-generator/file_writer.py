# file_writer.py — Tab-Delimited file I/O layer
from __future__ import annotations

import os
from typing import List


class FileWriter:
    """Writes rows of string data as a tab-delimited text file.

    Output format matches Excel "Save As → Text (Tab delimited) (*.txt)":
      - Encoding  : UTF-16 LE with BOM  (Windows standard for tab-delimited text)
      - Delimiter : Tab character (\\t)
      - Line ending: CRLF (\\r\\n)  — Windows line ending expected by DTW
    """

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir

    def write_tab_file(self, filename: str, rows: List[List[str]]) -> str:
        """Write *rows* to *filename* as a UTF-16 LE tab-delimited file.

        Args:
            filename: Target filename, e.g. ``TF_Head.txt``.
            rows:     List of rows; each row is a list of string values.

        Returns:
            The absolute path of the written file.

        Raises:
            IOError / OSError: If the file cannot be written.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)

        # UTF-16 LE with BOM + CRLF line endings = identical to Excel tab-delimited export
        with open(filepath, mode="w", encoding="utf-16", newline="") as fh:
            for row in rows:
                fh.write("\t".join(row) + "\r\n")

        return os.path.abspath(filepath)
