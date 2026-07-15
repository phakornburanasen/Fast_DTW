# tf_service.py — Business logic layer: full pipeline orchestration
from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from batch_runner import BatchRunnerException, run_dtw_batch
from config import OUTPUT_DIR
from file_manager import (
    FileManagerException,
    backup_tf_files,
    clear_temp_files,
    copy_tf_files_to_bak,
    restore_backup_to_template,
)
from file_writer import FileWriter
from schemas import Document, GenerateResponse, ResendResponse, StepStatus, TFRequest

if TYPE_CHECKING:
    from log_service import LogService


class FileWriteException(Exception):
    """Raised when an I/O error occurs while writing a TF file."""


# ---------------------------------------------------------------------------
# Canonical column orders (SAP B1 import format)
# ---------------------------------------------------------------------------

_HEAD_COLUMNS: List[str] = [
    "RecordKey",
    "DocEntry",
    "Address",
    "CardCode",
    "CardName",
    "Comments",
    "ContactPerson",
    "DocDate",
    "FromWarehouse",
    "JournalMemo",
    "PriceList",
    "Reference1",
    "Reference2",
    "SalesPersonCode",
    "Series",
    "TaxDate",
    "DocObjectCode",
]

_DETAIL_COLUMNS: List[str] = [
    "RecordKey",
    "LineNum",
    "Currency",
    "DiscountPercent",
    "Factor2",
    "Factor3",
    "Factor4",
    "Factor",
    "ItemCode",
    "ItemDescription",
    "Price",
    "ProjectCode",
    "Quantity",
    "Rate",
    "SerialNumber",
    "VendorNum",
    "WarehouseCode",
]


def _str(v) -> str:
    """Convert any value to string; treat None as empty string."""
    if v is None:
        return ""
    return str(v)


def _batch_detail(batch_result: dict) -> str:
    detail = f"pid={batch_result['pid']}"
    launcher = batch_result.get("launcher")
    if launcher:
        detail += f", launcher={launcher}"
    status = batch_result.get("status")
    if status:
        detail += f", status={status}"
    exit_code = batch_result.get("exit_code")
    if exit_code is not None:
        detail += f", exit_code={exit_code}"
    process_wait_seconds = batch_result.get("process_wait_seconds")
    if process_wait_seconds is not None:
        detail += f", process_wait_seconds={process_wait_seconds}"
    log_file = batch_result.get("log_file")
    if log_file:
        detail += f", log_file={log_file}"
    temp_cleanup = batch_result.get("temp_cleanup")
    if temp_cleanup and temp_cleanup.get("enabled"):
        detail += (
            f", temp_deleted={temp_cleanup.get('deleted', 0)}"
            f", temp_skipped={temp_cleanup.get('skipped', 0)}"
        )
    return detail


def _batch_exception_detail(exc: BatchRunnerException) -> str:
    """Build a readable detail string from a BatchRunnerException response."""
    response = getattr(exc, "response", {}) or {}
    if not response:
        return str(exc)

    parts = [str(exc)]
    for key in ("status", "failed_step", "exit_code", "dtw_pid", "log_file"):
        value = response.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    errors = response.get("errors") or []
    if errors:
        parts.append(f"errors={' | '.join(str(err) for err in errors[:3])}")
    return ", ".join(parts)


def _completed_at() -> str:
    """Return the local completion timestamp for API responses."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TFService:
    """Orchestrates the full 4-step pipeline."""

    def __init__(self, output_dir: str = OUTPUT_DIR, log_service: Optional["LogService"] = None) -> None:
        self._output_dir = output_dir
        self._writer = FileWriter(output_dir)
        self._log_service = log_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_tf_files(self, request: TFRequest) -> GenerateResponse:
        """Run the full pipeline:

        Step 1 — Clear temp files (TF_Head.txt / TF_Detail.txt) from output dir.
        Step 2 — Write new TF_Head.txt and TF_Detail.txt.
        Step 3 — Run DTW batch file (call_dtw_use_xml.bat).
        Step 4 — Backup TF files into bak_file/ with timestamp prefix.

        Returns GenerateResponse with per-step status for the frontend.
        """
        steps: List[StepStatus] = []
        head_path = ""
        detail_path = ""
        backup_paths: List[str] = []

        # ----------------------------------------------------------------
        # Step 1: Clear temp files
        # ----------------------------------------------------------------
        try:
            deleted = clear_temp_files(self._output_dir)
            steps.append(StepStatus(
                step="1_clear_temp",
                success=True,
                message=f"Cleared {len(deleted)} temp file(s)",
                detail=", ".join(deleted) if deleted else "No files to clear",
            ))
        except FileManagerException as exc:
            steps.append(StepStatus(
                step="1_clear_temp",
                success=False,
                message="Failed to clear temp files",
                detail=str(exc),
            ))
            return self._fail_response(
                "Pipeline failed at Step 1: clear temp files",
                steps,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 2: Write TF files
        # ----------------------------------------------------------------
        try:
            head_rows = self._build_head_rows(request.integration_profile, request.documents)
            detail_rows = self._build_detail_rows(request.integration_profile, request.documents)
            head_path = self._writer.write_tab_file("TF_Head.txt", head_rows)
            detail_path = self._writer.write_tab_file("TF_Detail.txt", detail_rows)
            steps.append(StepStatus(
                step="2_write_files",
                success=True,
                message="TF_Head.txt and TF_Detail.txt written successfully",
                detail=f"{head_path}, {detail_path}",
            ))
        except (IOError, OSError) as exc:
            steps.append(StepStatus(
                step="2_write_files",
                success=False,
                message="Failed to write TF files",
                detail=str(exc),
            ))
            return self._fail_response(
                "Pipeline failed at Step 2: write TF files",
                steps,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 3: Run DTW batch
        # ----------------------------------------------------------------
        try:
            batch_result = run_dtw_batch()
            steps.append(StepStatus(
                step="3_run_batch",
                success=True,
                message=f"DTW batch launched, waited {batch_result['wait_seconds']}s for completion",
                detail=_batch_detail(batch_result),
            ))
        except BatchRunnerException as exc:
            steps.append(StepStatus(
                step="3_run_batch",
                success=False,
                message="DTW batch failed",
                detail=str(exc),
            ))
            return self._fail_response(
                "Pipeline failed at Step 3: run DTW batch",
                steps,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 4: Backup TF files
        # ----------------------------------------------------------------
        try:
            moved = backup_tf_files(self._output_dir)
            backup_paths = [dst for _, dst in moved]
            steps.append(StepStatus(
                step="4_backup_files",
                success=True,
                message=f"Backed up {len(moved)} file(s) to bak_file/",
                detail=", ".join(backup_paths) if backup_paths else "No files to backup",
            ))
        except FileManagerException as exc:
            steps.append(StepStatus(
                step="4_backup_files",
                success=False,
                message="Failed to backup TF files",
                detail=str(exc),
            ))
            return self._fail_response(
                "Pipeline failed at Step 4: backup files",
                steps,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # All steps succeeded
        # ----------------------------------------------------------------
        return GenerateResponse(
            success=True,
            message="Pipeline completed successfully",
            status="COMPLETED",
            request_id=request.request_id,
            completed_at=_completed_at(),
            request_by=request.requested_by,
            files=[head_path, detail_path],
            steps=steps,
            backup_files=backup_paths,
        )

    def process_queued_job(
        self,
        job_id: int,
        request: TFRequest,
        log_service: Optional["LogService"] = None,
    ) -> GenerateResponse:
        """Run the full pipeline for a queued job (with DB logging).

        NEW step order:
            Step 1 — clear_temp
            Step 2 — write_files
            Step 3 — backup_files  (COPY before batch, original stays for DTW)
            Step 4 — run_batch
            Step 5 — complete
        """
        _log = log_service if log_service is not None else self._log_service

        if _log is not None:
            _log.log_processing(job_id)

        steps: List[StepStatus] = []
        head_path = ""
        detail_path = ""
        backup_paths: List[str] = []

        # ----------------------------------------------------------------
        # Step 1: Clear temp files
        # ----------------------------------------------------------------
        try:
            deleted = clear_temp_files(self._output_dir)
            step = StepStatus(
                step="1_clear_temp",
                success=True,
                message=f"Cleared {len(deleted)} temp file(s)",
                detail=", ".join(deleted) if deleted else "No files to clear",
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
        except FileManagerException as exc:
            step = StepStatus(
                step="1_clear_temp", success=False,
                message="Failed to clear temp files", detail=str(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return self._fail_response(
                "Pipeline failed at Step 1: clear temp files",
                steps,
                job_id=job_id,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 2: Write TF files
        # ----------------------------------------------------------------
        try:
            head_rows = self._build_head_rows(request.integration_profile, request.documents)
            detail_rows = self._build_detail_rows(request.integration_profile, request.documents)
            head_path = self._writer.write_tab_file("TF_Head.txt", head_rows)
            detail_path = self._writer.write_tab_file("TF_Detail.txt", detail_rows)
            step = StepStatus(
                step="2_write_files",
                success=True,
                message="TF_Head.txt and TF_Detail.txt written successfully",
                detail=f"{head_path}, {detail_path}",
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
        except (IOError, OSError) as exc:
            step = StepStatus(
                step="2_write_files", success=False,
                message="Failed to write TF files", detail=str(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return self._fail_response(
                "Pipeline failed at Step 2: write TF files",
                steps,
                job_id=job_id,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 3: Backup files (COPY — originals stay for DTW)
        # ----------------------------------------------------------------
        try:
            copied = copy_tf_files_to_bak(self._output_dir)
            backup_paths = [dst for _, dst in copied]
            # Identify head and detail backup paths by filename
            head_bak = next((d for _, d in copied if "TF_Head" in d), "")
            detail_bak = next((d for _, d in copied if "TF_Detail" in d), "")
            step = StepStatus(
                step="3_backup_files",
                success=True,
                message=f"Backed up {len(copied)} file(s) to bak_file/ (originals kept for DTW)",
                detail=", ".join(backup_paths),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                if head_bak and detail_bak:
                    _log.log_backup_paths(job_id, head_bak, detail_bak)
        except FileManagerException as exc:
            step = StepStatus(
                step="3_backup_files", success=False,
                message="Failed to backup TF files", detail=str(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return self._fail_response(
                "Pipeline failed at Step 3: backup files",
                steps,
                job_id=job_id,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # ----------------------------------------------------------------
        # Step 4: Run DTW batch
        # ----------------------------------------------------------------
        try:
            batch_result = run_dtw_batch(job_id=job_id)
            step = StepStatus(
                step="4_run_batch",
                success=True,
                message=f"DTW batch launched, waited {batch_result['wait_seconds']}s for completion",
                detail=_batch_detail(batch_result),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
        except BatchRunnerException as exc:
            step = StepStatus(
                step="4_run_batch", success=False,
                message="DTW batch failed", detail=_batch_exception_detail(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return self._fail_response(
                "Pipeline failed at Step 4: run DTW batch",
                steps,
                job_id=job_id,
                request_id=request.request_id,
                request_by=request.requested_by,
            )

        # All steps succeeded
        if _log is not None:
            _log.log_completed(job_id)

        return GenerateResponse(
            success=True,
            message="Pipeline completed successfully",
            job_id=job_id,
            status="COMPLETED",
            request_id=request.request_id,
            completed_at=_completed_at(),
            request_by=request.requested_by,
            files=[head_path, detail_path],
            steps=steps,
            backup_files=backup_paths,
        )

    def resend_job(
        self,
        job_id: int,
        head_bak_path: str,
        detail_bak_path: str,
        log_service: Optional["LogService"] = None,
    ) -> ResendResponse:
        """Retry a previously failed job using its archived backup files.

        Steps:
            1. Restore backup files from bak_file/ → Template/
            2. Run DTW batch
            3. Update job status

        Args:
            job_id:           The job to retry.
            head_bak_path:    Absolute path to the backed-up TF_Head file.
            detail_bak_path:  Absolute path to the backed-up TF_Detail file.
            log_service:      Optional override (for tests).
        """
        _log = log_service if log_service is not None else self._log_service
        steps: List[StepStatus] = []

        if _log is not None:
            _log.log_processing(job_id)

        # ----------------------------------------------------------------
        # Resend Step 1: Restore backup files to Template/
        # ----------------------------------------------------------------
        try:
            head_dst, detail_dst = restore_backup_to_template(
                head_bak_path, detail_bak_path, self._output_dir
            )
            step = StepStatus(
                step="resend_1_restore",
                success=True,
                message="Backup files restored to Template directory",
                detail=f"{head_dst}, {detail_dst}",
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
        except FileManagerException as exc:
            step = StepStatus(
                step="resend_1_restore", success=False,
                message="Failed to restore backup files", detail=str(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return ResendResponse(
                success=False, message=f"Resend failed: {exc}",
                job_id=job_id, status="FAILED", steps=steps,
            )

        # ----------------------------------------------------------------
        # Resend Step 2: Run DTW batch
        # ----------------------------------------------------------------
        try:
            batch_result = run_dtw_batch(job_id=f"resend-{job_id}")
            step = StepStatus(
                step="resend_2_run_batch",
                success=True,
                message=f"DTW batch launched, waited {batch_result['wait_seconds']}s",
                detail=_batch_detail(batch_result),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
        except BatchRunnerException as exc:
            step = StepStatus(
                step="resend_2_run_batch", success=False,
                message="DTW batch failed on resend", detail=_batch_exception_detail(exc),
            )
            steps.append(step)
            if _log is not None:
                _log.log_step(job_id, step)
                _log.log_failed(job_id, str(exc))
            return ResendResponse(
                success=False, message=f"Resend failed at DTW batch: {exc}",
                job_id=job_id, status="FAILED", steps=steps,
            )

        if _log is not None:
            _log.log_completed(job_id)

        return ResendResponse(
            success=True,
            message="Resend completed successfully",
            job_id=job_id,
            status="COMPLETED",
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fail_response(
        message: str,
        steps: List[StepStatus],
        job_id: Optional[int] = None,
        request_id: Optional[str] = None,
        request_by: Optional[str] = None,
    ) -> GenerateResponse:
        return GenerateResponse(
            success=False,
            message=message,
            job_id=job_id,
            status="FAILED",
            request_id=request_id,
            completed_at=_completed_at(),
            request_by=request_by,
            files=[],
            steps=steps,
            backup_files=[],
        )

    def _build_head_rows(
        self, profile: str, documents: List[Document]
    ) -> List[List[str]]:
        """Build TF_Head rows.

        Structure:
            Row 0  : header (column names)
            Row 1  : RAGTAG marker — RecordKey=profile, all other columns empty
            Row 2+ : one data row per document
                     RecordKey = record_key, rest from head_csv
        """
        rows: List[List[str]] = [list(_HEAD_COLUMNS)]
        rows.append([profile] + [""] * (len(_HEAD_COLUMNS) - 1))  # marker

        for doc in documents:
            h = doc.head_csv
            rows.append([
                _str(doc.record_key),
                _str(h.DocEntry),
                _str(h.Address),
                _str(h.CardCode),
                _str(h.CardName),
                _str(h.Comments),
                _str(h.ContactPerson),
                _str(h.DocDate),
                _str(h.FromWarehouse),
                _str(h.JournalMemo),
                _str(h.PriceList),
                _str(h.Reference1),
                _str(h.Reference2),
                _str(h.SalesPersonCode),
                _str(h.Series),
                _str(h.TaxDate),
                _str(h.DocObjectCode),
            ])

        return rows

    def _build_detail_rows(
        self, profile: str, documents: List[Document]
    ) -> List[List[str]]:
        """Build TF_Detail rows.

        Structure:
            Row 0  : header (column names)
            Row 1  : single RAGTAG marker — RecordKey=profile, all other columns empty
            Row 2+ : one data row per detail line across ALL documents
                     RecordKey = record_key, LineNum = actual LineNum
        """
        rows: List[List[str]] = [list(_DETAIL_COLUMNS)]
        rows.append([profile] + [""] * (len(_DETAIL_COLUMNS) - 1))  # marker

        for doc in documents:
            rk = _str(doc.record_key)
            for detail in doc.detail_csv:
                rows.append([
                    rk,
                    _str(detail.LineNum),
                    _str(detail.Currency),
                    _str(detail.DiscountPercent),
                    _str(detail.Factor2),
                    _str(detail.Factor3),
                    _str(detail.Factor4),
                    _str(detail.Factor),
                    _str(detail.ItemCode),
                    _str(detail.ItemDescription),
                    _str(detail.Price),
                    _str(detail.ProjectCode),
                    _str(detail.Quantity),
                    _str(detail.Rate),
                    _str(detail.SerialNumber),
                    _str(detail.VendorNum),
                    _str(detail.WarehouseCode),
                ])

        return rows
