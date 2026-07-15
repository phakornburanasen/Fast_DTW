# db/log_repository.py — Data-access functions for TF job tracking tables
# All functions accept an explicit connection so they are unit-testable with mocks.
#
# NOTE: tf_job_log.job_id remains the internal INT IDENTITY primary key.
# tf_job_log.job_no is the public YYYYMMDD### id returned by the API.
from __future__ import annotations

from typing import Dict, List, Optional

import pyodbc


# ---------------------------------------------------------------------------
# tf_job_log — INSERT
# ---------------------------------------------------------------------------

def insert_job(
    conn: pyodbc.Connection,
    request_id: str,
    integration_profile: str,
    requested_by: str,
    requested_at: str,
    source_system: str,
) -> tuple[int, int]:
    """Insert a job and return (internal job_id, public YYYYMMDD### job_no)."""
    sql = """
        DECLARE @today CHAR(8) = CONVERT(CHAR(8), GETDATE(), 112);
        DECLARE @prefix BIGINT = CAST(@today AS BIGINT) * 1000;
        DECLARE @job_no BIGINT;

        SELECT @job_no = ISNULL(MAX(job_no), @prefix) + 1
        FROM tf_job_log WITH (UPDLOCK, HOLDLOCK)
        WHERE job_no >= @prefix
          AND job_no <  @prefix + 1000;

        IF @job_no >= @prefix + 1000
        BEGIN
            THROW 51001, 'Daily job_no sequence exceeded 999 jobs.', 1;
        END;

        INSERT INTO tf_job_log
            (job_no, request_id, integration_profile, requested_by, requested_at,
             source_system, status)
        OUTPUT INSERTED.job_id, INSERTED.job_no
        VALUES (@job_no, ?, ?, ?, ?, ?, 'RECEIVED')
    """
    cursor = conn.cursor()
    cursor.execute(sql, request_id, integration_profile, requested_by,
                   requested_at, source_system)
    row = cursor.fetchone()
    conn.commit()
    return int(row[0]), int(row[1])


def update_job_status(
    conn: pyodbc.Connection,
    job_id: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update job status by public job_no, with legacy job_id fallback."""
    sql = """
        UPDATE tf_job_log
        SET    status        = ?,
               error_message = ?,
               updated_at    = GETDATE()
        WHERE  job_no = ?
           OR  job_id = TRY_CONVERT(INT, ?)
    """
    cursor = conn.cursor()
    cursor.execute(sql, status, error_message, job_id, job_id)
    conn.commit()


def update_job_backup_paths(
    conn: pyodbc.Connection,
    job_id: int,
    head_backup_path: str,
    detail_backup_path: str,
) -> None:
    """Store backup paths by public job_no, with legacy job_id fallback."""
    sql = """
        UPDATE tf_job_log
        SET    head_backup_path   = ?,
               detail_backup_path = ?,
               updated_at         = GETDATE()
        WHERE  job_no = ?
           OR  job_id = TRY_CONVERT(INT, ?)
    """
    cursor = conn.cursor()
    cursor.execute(sql, head_backup_path, detail_backup_path, job_id, job_id)
    conn.commit()


# ---------------------------------------------------------------------------
# tf_job_step
# ---------------------------------------------------------------------------

def insert_step(
    conn: pyodbc.Connection,
    job_id: int,
    step_name: str,
    success: bool,
    message: str,
    detail: Optional[str] = None,
) -> None:
    """Insert a processing step record using public job_no or legacy job_id."""
    sql = """
        DECLARE @internal_job_id INT;

        SELECT @internal_job_id = job_id
        FROM tf_job_log
        WHERE job_no = ?
           OR job_id = TRY_CONVERT(INT, ?);

        IF @internal_job_id IS NULL
        BEGIN
            THROW 51002, 'Job was not found for step insert.', 1;
        END;

        INSERT INTO tf_job_step (job_id, step_name, success, message, detail)
        VALUES (@internal_job_id, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    cursor.execute(
        sql,
        job_id,
        job_id,
        step_name,
        1 if success else 0,
        message,
        detail,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# tf_job_document
# ---------------------------------------------------------------------------

def insert_document(
    conn: pyodbc.Connection,
    job_id: int,
    record_key: str,
    transfer_no: str,
    doc_date: str,
    from_warehouse: str,
    series: str,
    comments: str,
) -> int:
    """Insert a document row. Returns the generated doc_id."""
    sql = """
        INSERT INTO tf_job_document
            (job_id, record_key, transfer_no, doc_date, from_warehouse, series, comments)
        OUTPUT INSERTED.doc_id
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    cursor.execute(sql, job_id, record_key, transfer_no, doc_date,
                   from_warehouse, series, comments)
    row = cursor.fetchone()
    conn.commit()
    return int(row[0])


# ---------------------------------------------------------------------------
# tf_job_item
# ---------------------------------------------------------------------------

def insert_item(
    conn: pyodbc.Connection,
    doc_id: int,
    job_id: int,
    line_num: int,
    item_code: str,
    quantity: str,
    warehouse_code: str,
) -> None:
    """Insert a single item/detail-line row."""
    sql = """
        INSERT INTO tf_job_item
            (doc_id, job_id, line_num, item_code, quantity, warehouse_code)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    cursor.execute(sql, doc_id, job_id, line_num, item_code, quantity, warehouse_code)
    conn.commit()


# ---------------------------------------------------------------------------
# tf_job_log — SELECT single job
# ---------------------------------------------------------------------------

def get_job_by_id(
    conn: pyodbc.Connection,
    job_id: int,
) -> Optional[Dict]:
    """Return one job row by internal job_id."""
    sql = """
        SELECT
            job_id, request_id, integration_profile, requested_by,
            CONVERT(VARCHAR(19), requested_at, 120) AS requested_at,
            source_system, status, error_message,
            head_backup_path, detail_backup_path,
            CONVERT(VARCHAR(19), created_at, 120) AS created_at,
            CONVERT(VARCHAR(19), updated_at, 120) AS updated_at
        FROM tf_job_log
        WHERE job_id = ?
    """
    cursor = conn.cursor()
    cursor.execute(sql, job_id)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def get_job_by_job_no(
    conn: pyodbc.Connection,
    job_no: int,
) -> Optional[Dict]:
    """Return one job row by public YYYYMMDD### job_no."""
    sql = """
        SELECT
            job_no AS job_id, request_id, integration_profile, requested_by,
            CONVERT(VARCHAR(19), requested_at, 120) AS requested_at,
            source_system, status, error_message,
            head_backup_path, detail_backup_path,
            CONVERT(VARCHAR(19), created_at, 120) AS created_at,
            CONVERT(VARCHAR(19), updated_at, 120) AS updated_at
        FROM tf_job_log
        WHERE job_no = ?
    """
    cursor = conn.cursor()
    cursor.execute(sql, job_no)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def get_failed_job_by_item_code(
    conn: pyodbc.Connection,
    item_code: str,
) -> Optional[Dict]:
    """Return the most recent non-COMPLETED job that contains item_code."""
    sql = """
        SELECT TOP 1
            l.job_no AS job_id, l.request_id, l.integration_profile, l.requested_by,
            CONVERT(VARCHAR(19), l.requested_at, 120) AS requested_at,
            l.source_system, l.status, l.error_message,
            l.head_backup_path, l.detail_backup_path,
            CONVERT(VARCHAR(19), l.created_at, 120) AS created_at,
            CONVERT(VARCHAR(19), l.updated_at, 120) AS updated_at
        FROM  tf_job_log      AS l
        JOIN  tf_job_item     AS i ON i.job_id = l.job_id
        WHERE i.item_code = ?
          AND l.status    <> 'COMPLETED'
        ORDER BY l.created_at DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, item_code)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def get_failed_job_by_request_id(
    conn: pyodbc.Connection,
    request_id: str,
) -> Optional[Dict]:
    """Return the most recent non-COMPLETED job for a request_id."""
    sql = """
        SELECT TOP 1
            job_no AS job_id, request_id, integration_profile, requested_by,
            CONVERT(VARCHAR(19), requested_at, 120) AS requested_at,
            source_system, status, error_message,
            head_backup_path, detail_backup_path,
            CONVERT(VARCHAR(19), created_at, 120) AS created_at,
            CONVERT(VARCHAR(19), updated_at, 120) AS updated_at
        FROM tf_job_log
        WHERE request_id = ?
          AND status    <> 'COMPLETED'
        ORDER BY created_at DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, request_id)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# tf_job_log — SELECT all jobs (paginated)
# ---------------------------------------------------------------------------

def get_all_jobs(
    conn: pyodbc.Connection,
    status: Optional[str] = None,
    status_not: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    created_at_from: Optional[str] = None,
    created_at_to: Optional[str] = None,
) -> List[Dict]:
    """Return a paginated list of jobs, optionally filtered by status/date.

    Args:
        status: Filter by job status (RECEIVED/PROCESSING/COMPLETED/FAILED).
                Pass None to return all statuses.
        status_not: Exclude this job status.
        limit:  Max rows to return (default 50, max 500).
        offset: Row offset for pagination (default 0).
        created_at_from: Inclusive created_at lower bound.
        created_at_to: Exclusive created_at upper bound.
    """
    limit = min(limit, 500)

    where_clauses = []
    params = []
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if status_not:
        where_clauses.append("status <> ?")
        params.append(status_not)
    if created_at_from and created_at_to:
        where_clauses.append("created_at >= ? AND created_at < ?")
        params.extend([created_at_from, created_at_to])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        SELECT
            job_no AS job_id, request_id, integration_profile, requested_by,
            CONVERT(VARCHAR(19), requested_at, 120) AS requested_at,
            source_system, status, error_message,
            head_backup_path, detail_backup_path,
            CONVERT(VARCHAR(19), created_at, 120) AS created_at,
            CONVERT(VARCHAR(19), updated_at, 120) AS updated_at
        FROM tf_job_log
        {where_sql}
        ORDER BY created_at DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    params.extend([offset, limit])
    cursor = conn.cursor()
    cursor.execute(sql, *params)

    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def count_jobs(
    conn: pyodbc.Connection,
    status: Optional[str] = None,
    status_not: Optional[str] = None,
    created_at_from: Optional[str] = None,
    created_at_to: Optional[str] = None,
) -> int:
    """Return total job count, optionally filtered by status/date."""
    where_clauses = []
    params = []
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if status_not:
        where_clauses.append("status <> ?")
        params.append(status_not)
    if created_at_from and created_at_to:
        where_clauses.append("created_at >= ? AND created_at < ?")
        params.extend([created_at_from, created_at_to])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"SELECT COUNT(*) FROM tf_job_log {where_sql}"
    cursor = conn.cursor()
    cursor.execute(sql, *params)
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def get_items_by_job_id(
    conn: pyodbc.Connection,
    job_id: int,
) -> List[Dict]:
    """Return all item_code records for a public job_no or legacy job_id."""
    sql = """
        SELECT
            i.item_id,
            i.line_num,
            i.item_code,
            i.quantity,
            i.warehouse_code,
            i.status          AS item_status,
            d.transfer_no,
            d.record_key,
            CONVERT(VARCHAR(19), i.created_at, 120) AS created_at
        FROM  tf_job_item     AS i
        JOIN  tf_job_document AS d ON d.doc_id = i.doc_id
        JOIN  tf_job_log      AS l ON l.job_id = i.job_id
        WHERE l.job_no = ?
           OR l.job_id = TRY_CONVERT(INT, ?)
        ORDER BY d.record_key, i.line_num
    """
    cursor = conn.cursor()
    cursor.execute(sql, job_id, job_id)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# tf_job_item — SELECT by item_code
# ---------------------------------------------------------------------------

def get_items_by_item_code(
    conn: pyodbc.Connection,
    item_code: str,
) -> List[Dict]:
    """Return all item tracking records matching item_code.

    JOIN path: tf_job_item → tf_job_document → tf_job_log
    Results ordered by tf_job_item.created_at DESC.
    """
    sql = """
        SELECT
            l.job_no AS job_id,
            i.item_code,
            i.line_num,
            i.quantity,
            i.warehouse_code,
            i.status          AS item_status,
            d.transfer_no,
            d.doc_date,
            d.from_warehouse,
            l.request_id,
            l.status          AS job_status,
            CONVERT(VARCHAR(19), l.requested_at, 120)  AS requested_at,
            CONVERT(VARCHAR(19), i.created_at,   120)  AS created_at
        FROM  tf_job_item     AS i
        JOIN  tf_job_document AS d ON d.doc_id = i.doc_id
        JOIN  tf_job_log      AS l ON l.job_id = i.job_id
        WHERE i.item_code = ?
        ORDER BY i.created_at DESC
    """
    cursor = conn.cursor()
    cursor.execute(sql, item_code)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
