# file_manager.py — Backup and cleanup utilities for TF output files
from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import List, Tuple

# Files produced each run
_TF_FILES = ["TF_Head.txt", "TF_Detail.txt"]

# Subfolder inside output_dir where backups are stored
_BAK_DIR = "bak_file"


class FileManagerException(Exception):
    """Raised when a file management operation fails."""


def clear_temp_files(output_dir: str) -> List[str]:
    """Delete TF_Head.txt and TF_Detail.txt from *output_dir* if they exist.

    Returns a list of paths that were deleted.
    Pipeline Step 1.
    """
    deleted: List[str] = []
    for filename in _TF_FILES:
        path = os.path.join(output_dir, filename)
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(path)
            except OSError as exc:
                raise FileManagerException(
                    f"Failed to delete temp file '{path}': {exc}"
                ) from exc
    return deleted


def copy_tf_files_to_bak(output_dir: str) -> List[Tuple[str, str]]:
    """COPY TF_Head.txt and TF_Detail.txt into *output_dir*/bak_file/
    with a YYYYMMDD_HHMMSS_ timestamp prefix.

    Original files remain in *output_dir* so DTW can still read them.
    Pipeline Step 3 — runs BEFORE run_batch.

    Returns list of (original_path, backup_path) for files that existed.
    """
    bak_dir = os.path.join(output_dir, _BAK_DIR)
    os.makedirs(bak_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    copied: List[Tuple[str, str]] = []

    for filename in _TF_FILES:
        src = os.path.join(output_dir, filename)
        if not os.path.exists(src):
            continue
        dst = os.path.join(bak_dir, f"{timestamp}_{filename}")
        try:
            shutil.copy2(src, dst)          # copy2 preserves metadata
            copied.append((src, dst))
        except OSError as exc:
            raise FileManagerException(
                f"Failed to copy '{src}' → '{dst}': {exc}"
            ) from exc

    return copied


def restore_backup_to_template(
    head_bak_path: str,
    detail_bak_path: str,
    output_dir: str,
) -> Tuple[str, str]:
    """Copy backed-up files back to *output_dir* as TF_Head.txt / TF_Detail.txt.

    Used by the resend pipeline to restore the archived files before re-running DTW.

    Args:
        head_bak_path:   Absolute path to the backed-up TF_Head file.
        detail_bak_path: Absolute path to the backed-up TF_Detail file.
        output_dir:      Template directory where DTW reads from.

    Returns:
        (head_dst, detail_dst) — paths of the restored files.

    Raises:
        FileManagerException: if a backup file is missing or copy fails.
    """
    os.makedirs(output_dir, exist_ok=True)

    results: List[str] = []
    for bak_path, filename in (
        (head_bak_path, "TF_Head.txt"),
        (detail_bak_path, "TF_Detail.txt"),
    ):
        if not os.path.exists(bak_path):
            raise FileManagerException(
                f"Backup file not found: '{bak_path}'"
            )
        dst = os.path.join(output_dir, filename)
        try:
            shutil.copy2(bak_path, dst)
            results.append(os.path.abspath(dst))
        except OSError as exc:
            raise FileManagerException(
                f"Failed to restore '{bak_path}' → '{dst}': {exc}"
            ) from exc

    return (results[0], results[1])


# ---------------------------------------------------------------------------
# Legacy alias — kept for backward compat with existing tests
# ---------------------------------------------------------------------------

def backup_tf_files(output_dir: str) -> List[Tuple[str, str]]:
    """Backward-compatible alias: MOVE files to bak_file/.

    Still used by the old generate_tf_files path and its tests.
    New pipeline uses copy_tf_files_to_bak() instead.
    """
    bak_dir = os.path.join(output_dir, _BAK_DIR)
    os.makedirs(bak_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    moved: List[Tuple[str, str]] = []

    for filename in _TF_FILES:
        src = os.path.join(output_dir, filename)
        if not os.path.exists(src):
            continue
        dst = os.path.join(bak_dir, f"{timestamp}_{filename}")
        try:
            shutil.move(src, dst)
            moved.append((src, dst))
        except OSError as exc:
            raise FileManagerException(
                f"Failed to backup '{src}' → '{dst}': {exc}"
            ) from exc

    return moved
