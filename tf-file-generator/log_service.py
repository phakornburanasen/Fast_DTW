# log_service.py — Business-logging layer between the pipeline and the DB
from __future__ import annotations

import sys
from typing import Optional

from db.connection import DBConnectionException, get_connection
from db.log_repository import (
    insert_document,
    insert_item,
    insert_job,
    insert_step,
    update_job_backup_paths,
    update_job_status,
)
from schemas import StepStatus, TFRequest


class LogService:
    """Persists job-lifecycle events to SQL Server.

    All methods swallow DB exceptions and write to stderr so a DB outage
    never crashes the main pipeline.
    """

    def __init__(self) -> None:
        try:
            self._conn = get_connection()
        except DBConnectionException as exc:
            print(f"[LogService] DB connection failed: {exc}", file=sys.stderr)
            self._conn = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_received(self, request: TFRequest) -> int:
        """Insert job + all documents/items. Returns public job_no (0 on failure)."""
        if self._conn is None:
            return 0
        try:
            db_job_id, job_no = insert_job(
                self._conn,
                request_id=request.request_id,
                integration_profile=request.integration_profile,
                requested_by=request.requested_by,
                requested_at=request.requested_at,
                source_system=request.source_system,
            )
            for doc in request.documents:
                doc_id = insert_document(
                    self._conn,
                    job_id=db_job_id,
                    record_key=str(doc.record_key),
                    transfer_no=doc.transfer_no,
                    doc_date=doc.doc_date,
                    from_warehouse=doc.head_csv.FromWarehouse,
                    series=doc.head_csv.Series,
                    comments=doc.head_csv.Comments,
                )
                for detail in doc.detail_csv:
                    insert_item(
                        self._conn,
                        doc_id=doc_id,
                        job_id=db_job_id,
                        line_num=int(detail.LineNum) if str(detail.LineNum).isdigit() else 0,
                        item_code=str(detail.ItemCode),
                        quantity=str(detail.Quantity),
                        warehouse_code=str(detail.WarehouseCode),
                    )
            return job_no
        except Exception as exc:
            print(f"[LogService] log_received error: {exc}", file=sys.stderr)
            return 0

    def log_processing(self, job_id: int) -> None:
        """Update job status to PROCESSING."""
        self._safe_update(job_id, "PROCESSING")

    def log_step(self, job_id: int, step: StepStatus) -> None:
        """Persist a single pipeline step record."""
        if self._conn is None or job_id == 0:
            return
        try:
            insert_step(
                self._conn,
                job_id=job_id,
                step_name=step.step,
                success=step.success,
                message=step.message,
                detail=step.detail,
            )
        except Exception as exc:
            print(f"[LogService] log_step error: {exc}", file=sys.stderr)

    def log_backup_paths(
        self,
        job_id: int,
        head_backup_path: str,
        detail_backup_path: str,
    ) -> None:
        """Store backup file paths on the job record."""
        if self._conn is None or job_id == 0:
            return
        try:
            update_job_backup_paths(
                self._conn, job_id, head_backup_path, detail_backup_path
            )
        except Exception as exc:
            print(f"[LogService] log_backup_paths error: {exc}", file=sys.stderr)

    def log_completed(self, job_id: int) -> None:
        """Update job status to COMPLETED."""
        self._safe_update(job_id, "COMPLETED")

    def log_failed(self, job_id: int, error_message: str) -> None:
        """Update job status to FAILED with the error message."""
        self._safe_update(job_id, "FAILED", error_message=error_message)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _safe_update(
        self,
        job_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        if self._conn is None or job_id == 0:
            return
        try:
            update_job_status(self._conn, job_id, status, error_message)
        except Exception as exc:
            print(f"[LogService] update_job_status({status}) error: {exc}", file=sys.stderr)
