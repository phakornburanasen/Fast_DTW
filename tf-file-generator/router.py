# router.py — API route definitions
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from db.connection import DBConnectionException, get_connection
from db.log_repository import (
    count_jobs,
    get_all_jobs,
    get_failed_job_by_item_code,
    get_failed_job_by_request_id,
    get_items_by_job_id,
    get_job_by_id,
    get_job_by_job_no,
)
from db.status_repository import get_item_status
from log_service import LogService
from schemas import (
    GenerateResponse,
    ItemStatusRecord,
    ItemStatusResponse,
    JobItemRecord,
    JobListResponse,
    JobRecord,
    ResendResponse,
    TFRequest,
)
from tf_service import TFService

router = APIRouter()
_log_service = LogService()
_service = TFService(log_service=_log_service)


def get_db():
    try:
        conn = get_connection()
        yield conn
    except DBConnectionException as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error: DB Connection Failed")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _make_job_record(row: Dict[str, Any], item_rows: list) -> JobRecord:
    """Convert a job DB row + item rows into a JobRecord."""
    items = [
        JobItemRecord(
            item_id=int(r["item_id"]),
            line_num=int(r["line_num"]),
            item_code=str(r["item_code"]),
            quantity=str(r["quantity"]),
            warehouse_code=str(r["warehouse_code"]),
            item_status=str(r["item_status"]),
            transfer_no=str(r["transfer_no"]),
            record_key=str(r["record_key"]),
            created_at=str(r["created_at"]),
        )
        for r in item_rows
    ]
    return JobRecord(
        job_id=int(row["job_id"]),
        request_id=str(row["request_id"]),
        integration_profile=str(row["integration_profile"]),
        requested_by=str(row["requested_by"]),
        requested_at=str(row["requested_at"]),
        source_system=str(row["source_system"]),
        status=str(row["status"]),
        error_message=row.get("error_message"),
        head_backup_path=row.get("head_backup_path"),
        detail_backup_path=row.get("detail_backup_path"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        items=items,
    )


def _parse_created_at_filter(created_at: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Convert yyyy-mm-dd or yyyy-mm into an inclusive/exclusive datetime range."""
    if not created_at:
        return None, None

    value = created_at.strip()
    try:
        if len(value) == 10:
            start = datetime.strptime(value, "%Y-%m-%d")
            end = start + timedelta(days=1)
        elif len(value) == 7:
            start = datetime.strptime(value, "%Y-%m")
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        else:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="created_at must be in yyyy-mm-dd or yyyy-mm format",
        )

    return (
        start.strftime("%Y-%m-%d 00:00:00"),
        end.strftime("%Y-%m-%d 00:00:00"),
    )


def _query_value(request: Request, *names: str) -> Optional[str]:
    """Return the first non-empty query value from multiple possible names."""
    for name in names:
        value = request.query_params.get(name)
        if value:
            return value
    return None


def _status_not_from_query(request: Request, explicit_status_not: Optional[str]) -> Optional[str]:
    """Support status_not/status_ne plus shorthand keys like status<>COMPLETED."""
    if explicit_status_not:
        return explicit_status_not

    for key, value in request.query_params.multi_items():
        if key in {"status_not", "status_ne"} and value:
            return value
        for operator in ("status<>", "status!="):
            if key.startswith(operator):
                return value or key[len(operator):]
    return None


# ============================================================================
# POST /generate-tf
# ============================================================================

@router.post(
    "/generate-tf",
    tags=["Transfer File"],
    summary="สร้างไฟล์ TF และส่งเข้า DTW",
    response_description="ยืนยันการรับงาน พร้อม job_id สำหรับติดตาม",
    responses={
        200: {
            "description": "งานถูกรับและใส่คิวเรียบร้อย",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Pipeline completed successfully",
                        "job_id": 20260714001,
                        "status": "COMPLETED",
                        "files": [],
                        "steps": [],
                        "backup_files": [],
                    }
                }
            },
        },
        422: {"description": "Payload ไม่ถูกต้อง (Pydantic validation error)"},
        500: {"description": "Internal server error"},
    },
)
async def generate_tf(
    request: TFRequest,
) -> GenerateResponse:
    """รับ JSON Payload, บันทึก log สถานะ **RECEIVED**, ใส่คิว แล้วตอบกลับทันที

    Pipeline ที่รันใน background:
    1. **clear_temp** — ลบไฟล์เก่าออกจาก Template/
    2. **write_files** — เขียน TF_Head.txt และ TF_Detail.txt
    3. **backup_files** — COPY ไปที่ bak_file/ (ต้นฉบับยังอยู่)
    4. **run_batch** — รัน call_dtw_use_xml.bat

    สถานะ job: `RECEIVED` → `PROCESSING` → `COMPLETED` / `FAILED`

    ใช้ **`GET /status/item_code/{item_code}`** เพื่อติดตามสถานะ
    หรือ **`POST /resend_job/item_code/{item_code}`** /
    **`POST /resend_job/request_id/{request_id}`** หากงานล้มเหลว
    """
    try:
        job_id = _log_service.log_received(request)
        return await run_in_threadpool(_service.process_queued_job, job_id, request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

# ============================================================================
# GET /status/item_code/{item_code}
# ============================================================================

@router.get(
    "/status/item_code/{item_code}",
    tags=["Status"],
    summary="ตรวจสอบสถานะตาม ItemCode",
    response_model=ItemStatusResponse,
    response_description="ประวัติทั้งหมดของ ItemCode นี้ เรียงจากใหม่ไปเก่า",
    responses={
        200: {
            "description": "ดึงข้อมูลสำเร็จ (อาจ records ว่างถ้าไม่พบ)",
            "content": {
                "application/json": {
                    "example": {
                        "item_code": "TH0230226055401",
                        "total": 1,
                        "records": [
                            {
                                "job_id": 20260714001,
                                "item_code": "TH0230226055401",
                                "line_num": 0,
                                "quantity": "1",
                                "warehouse_code": "INTRAN",
                                "item_status": "PROCESSING",
                                "transfer_no": "Test_TF01",
                                "doc_date": "2026-07-01",
                                "from_warehouse": "STORE2",
                                "request_id": "b7a8f1b0-7df2-4c8e-9e4c-26070001",
                                "job_status": "COMPLETED",
                                "requested_at": "2026-07-08 10:00:00",
                                "created_at": "2026-07-08 09:35:47",
                            }
                        ],
                    }
                }
            },
        },
        500: {"description": "DB connection failed"},
    },
)
async def get_item_status_endpoint(item_code: str, conn = Depends(get_db)) -> ItemStatusResponse:
    """ดึงประวัติการโอนสินค้าทั้งหมดของ **item_code** ที่ระบุ

    **item_status** — สถานะของ line item นั้น:
    - `PROCESSING` — อยู่ระหว่างดำเนินการ
    - `COMPLETED` — สำเร็จ

    **job_status** — สถานะของ job (TF request) ทั้งใบ:
    - `RECEIVED` → `PROCESSING` → `COMPLETED` / `FAILED`
        """
    try:
        rows = get_item_status(conn, item_code)
        records = [
            ItemStatusRecord(
                job_id=int(row["job_id"]),
                item_code=str(row["item_code"]),
                line_num=int(row["line_num"]),
                quantity=str(row["quantity"]),
                warehouse_code=str(row["warehouse_code"]),
                item_status=str(row["item_status"]),
                transfer_no=str(row["transfer_no"]),
                doc_date=str(row["doc_date"]),
                from_warehouse=str(row["from_warehouse"]),
                request_id=str(row["request_id"]),
                job_status=str(row["job_status"]),
                requested_at=str(row["requested_at"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]
        return ItemStatusResponse(
            item_code=item_code,
            records=records,
                        total=len(records),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

# ============================================================================
# POST /resend_job/item_code/{item_code}
# ============================================================================

@router.post(
    "/resend_job/item_code/{item_code}",
    tags=["Resend"],
    summary="ทำงานซ้ำสำหรับ ItemCode ที่ยังไม่สำเร็จ",
    response_model=ResendResponse,
    response_description="ผลการทำงานซ้ำ พร้อมสถานะแต่ละ step",
    responses={
        200: {
            "description": "Resend สำเร็จหรือล้มเหลว (ดู success field)",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Resend completed successfully",
                        "job_id": 20260714001,
                        "status": "COMPLETED",
                        "steps": [
                            {
                                "step": "resend_1_restore",
                                "success": True,
                                "message": "Backup files restored to Template directory",
                                "detail": "C:\\...\\TF_Head.txt, C:\\...\\TF_Detail.txt",
                            },
                            {
                                "step": "resend_2_run_batch",
                                "success": True,
                                "message": "DTW batch launched, waited 15s",
                                "detail": "pid=1234",
                            },
                        ],
                    }
                }
            },
        },
        404: {"description": "ไม่พบ job ที่ยังไม่สำเร็จสำหรับ item_code นี้"},
        400: {"description": "ไม่มี backup file path บันทึกไว้ใน DB"},
        500: {"description": "DB connection failed หรือ unexpected error"},
    },
)
async def resend_job_by_item_code(item_code: str, conn = Depends(get_db)) -> ResendResponse:
    """ค้นหา job ล่าสุดที่ **ยังไม่สำเร็จ** (status ≠ COMPLETED) ของ item_code นี้
    แล้วรัน DTW ใหม่โดยใช้ไฟล์ที่ backup ไว้

    **ขั้นตอน:**
    1. ค้นหา job ที่ `status <> COMPLETED` ล่าสุดของ item_code
    2. อ่าน `head_backup_path` และ `detail_backup_path` จาก DB
    3. Copy ไฟล์จาก `bak_file/` กลับไปที่ `Template/`
    4. รัน DTW batch อีกครั้ง
    5. อัปเดต status เป็น `COMPLETED` หรือ `FAILED`

    **เงื่อนไข:**
    - job ต้องมี backup path บันทึกไว้ใน DB (เกิดขึ้นเมื่อ pipeline ผ่าน step 3 แล้ว)
        - หาก job ไม่มี backup path (ล้มเหลวก่อน step 3) ต้องส่ง request ใหม่ผ่าน `/generate-tf`
    """
    # 1. หา job ที่ fail จาก item_code
    try:
        job = get_failed_job_by_item_code(conn, item_code)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No incomplete job found for item_code '{item_code}'",
        )

    job_id = int(job["job_id"])
    head_bak = job.get("head_backup_path") or ""
    detail_bak = job.get("detail_backup_path") or ""

    if not head_bak or not detail_bak:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Job {job_id} has no backup paths recorded. "
                "The job may have failed before the backup step. "
                "Please re-submit via POST /generate-tf instead."
            ),
        )

    # 2. รัน resend pipeline
    try:
        result = _service.resend_job(
            job_id=job_id,
            head_bak_path=head_bak,
            detail_bak_path=detail_bak,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# POST /resend_job/request_id/{request_id}
# ============================================================================

@router.post(
    "/resend_job/request_id/{request_id}",
    tags=["Resend"],
    summary="ทำงานซ้ำสำหรับ request_id ที่ยังไม่สำเร็จ",
    response_model=ResendResponse,
    response_description="ผลการทำงานซ้ำ พร้อมสถานะแต่ละ step",
    responses={
        200: {
            "description": "Resend สำเร็จหรือล้มเหลว (ดู success field)",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Resend completed successfully",
                        "job_id": 20260714001,
                        "status": "COMPLETED",
                        "steps": [
                            {
                                "step": "resend_1_restore",
                                "success": True,
                                "message": "Backup files restored to Template directory",
                                "detail": "C:\\...\\TF_Head.txt, C:\\...\\TF_Detail.txt",
                            },
                            {
                                "step": "resend_2_run_batch",
                                "success": True,
                                "message": "DTW batch launched, waited 15s",
                                "detail": "pid=1234",
                            },
                        ],
                    }
                }
            },
        },
        404: {"description": "ไม่พบ job ที่ยังไม่สำเร็จสำหรับ request_id นี้"},
        400: {"description": "ไม่มี backup file path บันทึกไว้ใน DB"},
        500: {"description": "DB connection failed หรือ unexpected error"},
    },
)
async def resend_job_by_request_id(request_id: str, conn = Depends(get_db)) -> ResendResponse:
    """ค้นหา job ล่าสุดที่ **ยังไม่สำเร็จ** (status ≠ COMPLETED) ของ request_id นี้
    แล้วรัน DTW ใหม่โดยใช้ไฟล์ที่ backup ไว้

    **ขั้นตอน:**
    1. ค้นหา job ที่ `status <> COMPLETED` ล่าสุดของ request_id
    2. อ่าน `head_backup_path` และ `detail_backup_path` จาก DB
    3. Copy ไฟล์จาก `bak_file/` กลับไปที่ `Template/`
    4. รัน DTW batch อีกครั้ง
    5. อัปเดต status เป็น `COMPLETED` หรือ `FAILED`

    **เงื่อนไข:**
    - job ต้องมี backup path บันทึกไว้ใน DB (เกิดขึ้นเมื่อ pipeline ผ่าน step backup แล้ว)
    - หาก job ไม่มี backup path ต้องส่ง request ใหม่ผ่าน `/generate-tf`
    """
    try:
        job = get_failed_job_by_request_id(conn, request_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No incomplete job found for request_id '{request_id}'",
        )

    job_id = int(job["job_id"])
    head_bak = job.get("head_backup_path") or ""
    detail_bak = job.get("detail_backup_path") or ""

    if not head_bak or not detail_bak:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Job {job_id} has no backup paths recorded. "
                "The job may have failed before the backup step. "
                "Please re-submit via POST /generate-tf instead."
            ),
        )

    try:
        result = _service.resend_job(
            job_id=job_id,
            head_bak_path=head_bak,
            detail_bak_path=detail_bak,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# POST /resend_job/job/{job_id}  — resend by job_id directly
# ============================================================================

@router.post(
    "/resend_job/job/{job_id}",
    tags=["Resend"],
    summary="ทำงานซ้ำโดยระบุ job_id โดยตรง",
    response_model=ResendResponse,
    response_description="ผลการทำงานซ้ำ พร้อมสถานะแต่ละ step",
    responses={
        200: {"description": "Resend สำเร็จหรือล้มเหลว (ดู success field)"},
        404: {"description": "ไม่พบ job_id นี้ในระบบ"},
        400: {
            "description": (
                "Job นี้ COMPLETED แล้ว ไม่จำเป็นต้อง resend "
                "หรือไม่มี backup path บันทึกไว้"
            )
        },
        500: {"description": "DB connection failed หรือ unexpected error"},
    },
)
async def resend_job_by_job_id(job_id: int, conn = Depends(get_db)) -> ResendResponse:
    """ทำงานซ้ำโดยใช้ **job_id** โดยตรง (ไม่ต้องระบุ item_code)

    เหมาะสำหรับกรณีที่ทราบ job_id จาก log หรือ response ของ `/generate-tf`

    **เงื่อนไขเดียวกับ** `POST /resend_job/item_code/{item_code}`:
    - job ต้องมี status ≠ COMPLETED
        - job ต้องมี backup path บันทึกไว้ใน DB
    """
    try:
        job = get_job_by_id(conn, job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.get("status") == "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is already COMPLETED. No resend needed.",
        )

    head_bak = job.get("head_backup_path") or ""
    detail_bak = job.get("detail_backup_path") or ""

    if not head_bak or not detail_bak:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Job {job_id} has no backup paths recorded. "
                "The job may have failed before the backup step. "
                "Please re-submit via POST /generate-tf instead."
            ),
        )

    try:
        result = _service.resend_job(
            job_id=job_id,
            head_bak_path=head_bak,
            detail_bak_path=detail_bak,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# POST /resend_job/job_no/{job_no}  — resend by public date-based job_no
# ============================================================================

@router.post(
    "/resend_job/job_no/{job_no}",
    tags=["Resend"],
    summary="ทำงานซ้ำโดยระบุ job_no รูปแบบวันที่",
    response_model=ResendResponse,
    response_description="ผลการทำงานซ้ำ โดยค้นหาจาก tf_job_log.job_no",
    responses={
        200: {
            "description": "Resend สำเร็จหรือล้มเหลว (ดู success field)",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Resend completed successfully",
                        "job_id": 20260714001,
                        "status": "COMPLETED",
                        "steps": [],
                    }
                }
            },
        },
        404: {"description": "ไม่พบ job_no นี้ใน tf_job_log.job_no"},
        400: {
            "description": (
                "Job นี้ COMPLETED แล้ว ไม่จำเป็นต้อง resend "
                "หรือไม่มี backup path บันทึกไว้"
            )
        },
        500: {"description": "DB connection failed หรือ unexpected error"},
    },
)
async def resend_job_by_job_no(job_no: int, conn = Depends(get_db)) -> ResendResponse:
    """ทำงานซ้ำโดยใช้ **tf_job_log.job_no** เช่น `20260714001`

    ต่างจาก `POST /resend_job/job/{job_id}` ซึ่งค้นหาจาก internal
    `tf_job_log.job_id` และใช้ความสัมพันธ์เดิมของตารางลูกผ่าน `job_id`.
    Endpoint นี้ค้นหาจาก `job_no` ก่อน แล้วส่งเลข `job_no` ให้ pipeline
    เพื่ออัปเดตสถานะและเขียน step ผ่าน mapping กลับไปยัง internal job_id.
    """
    try:
        job = get_job_by_job_no(conn, job_no)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job no {job_no} not found")

    if job.get("status") == "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail=f"Job no {job_no} is already COMPLETED. No resend needed.",
        )

    head_bak = job.get("head_backup_path") or ""
    detail_bak = job.get("detail_backup_path") or ""

    if not head_bak or not detail_bak:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Job no {job_no} has no backup paths recorded. "
                "The job may have failed before the backup step. "
                "Please re-submit via POST /generate-tf instead."
            ),
        )

    try:
        result = _service.resend_job(
            job_id=job_no,
            head_bak_path=head_bak,
            detail_bak_path=detail_bak,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============================================================================
# GET /jobs  — ดู job ทั้งหมด (paginated)
# ============================================================================

@router.get(
    "/jobs",
    tags=["Status"],
    summary="ดู job ทั้งหมด (รองรับ filter และ pagination)",
    response_model=JobListResponse,
    response_description="รายการ job เรียงจากใหม่ไปเก่า",
    responses={
        200: {
            "description": "รายการ job",
            "content": {
                "application/json": {
                    "example": {
                        "total": 120,
                        "limit": 20,
                        "offset": 0,
                        "status_filter": None,
                        "status_not_filter": None,
                        "created_at_filter": None,
                        "jobs": [
                            {
                                "job_id": 20260714001,
                                "request_id": "b7a8f1b0-7df2-4c8e-9e4c-26070001",
                                "integration_profile": "RAGTAG",
                                "requested_by": "T9334",
                                "requested_at": "2026-07-08 10:00:00",
                                "source_system": "STM",
                                "status": "COMPLETED",
                                "error_message": None,
                                "head_backup_path": "C:\\...\\20260708_100001_TF_Head.txt",
                                "detail_backup_path": "C:\\...\\20260708_100001_TF_Detail.txt",
                                "created_at": "2026-07-08 10:00:00",
                                "updated_at": "2026-07-08 10:00:16",
                            }
                        ],
                    }
                }
            },
        },
        500: {"description": "DB connection failed"},
    },
)
async def list_jobs(
    request: Request,
    status: Optional[str] = None,
    status_not: Optional[str] = Query(
        None,
        description="Exclude one status, e.g. COMPLETED. Alias status_ne is also supported.",
    ),
    status_ne: Optional[str] = Query(
        None,
        description="Alias for status_not. Example: status_ne=COMPLETED.",
    ),
    created_at: Optional[str] = Query(
        None,
        description="Filter by tf_job_log.created_at. Use yyyy-mm-dd for one day or yyyy-mm for one month.",
    ),
    limit: int = 20,
    offset: int = 0,
    conn = Depends(get_db)
) -> JobListResponse:
    """ดูรายการ job ทั้งหมด รองรับ filter และ pagination

    **Query Parameters:**

    | Parameter | Type | Default | คำอธิบาย |
    |-----------|------|---------|-----------|
    | `status` | string | (ทั้งหมด) | กรองตาม status: `RECEIVED` / `PROCESSING` / `COMPLETED` / `FAILED` |
    | `status_not` / `status_ne` | string | (ทั้งหมด) | ไม่เอา status ที่ระบุ เช่น `COMPLETED` |
    | `created_at` | string | (ทั้งหมด) | กรองตาม `tf_job_log.created_at`: `yyyy-mm-dd` หรือ `yyyy-mm` |
    | `limit` | int | `20` | จำนวน record ต่อหน้า (สูงสุด 500) |
    | `offset` | int | `0` | ข้าม N record แรก (สำหรับ pagination) |

    **ตัวอย่างการเรียก:**
    ```
    GET /jobs                                              ← ดึง Job ทั้งหมด (ค่าเริ่มต้น 20 รายการแรก)
    GET /jobs?status=FAILED                                ← ดึงเฉพาะ Job ที่มีสถานะ FAILED
    GET /jobs?status=COMPLETED&limit=50                    ← ดึงเฉพาะ Job ที่มีสถานะ COMPLETED จำนวน 50 รายการ
    GET /jobs?created_at=2026-07-10                        ← ดึงเฉพาะ Job ที่สร้างวันที่ 2026-07-10
    GET /jobs?created_at=2026-07                           ← ดึงเฉพาะ Job ที่สร้างในเดือน 2026-07
    GET /jobs?status_ne=COMPLETED&created_at=2026-07-10   ← ดึง Job วันที่ 2026-07-10 ที่สถานะไม่ใช่ COMPLETED
    GET /jobs?status=COMPLETED&created_at=2026-07-10      ← ดึง Job สถานะ COMPLETED ที่สร้างวันที่ 2026-07-10
    GET /jobs?status_ne=COMPLETED&created_at=2026-07      ← ดึง Job ในเดือน 2026-07 ที่สถานะไม่ใช่ COMPLETED
    GET /jobs?status=COMPLETED&created_at=2026-07         ← ดึง Job สถานะ COMPLETED ที่สร้างในเดือน 2026-07
    GET /jobs?limit=10&offset=20                           ← ดึง 10 รายการ เริ่มจากลำดับที่ 21 (หน้า 3, รายการ 21-30)

    Parameters
    status      ← กรองตามสถานะ Job (RECEIVED, PROCESSING, COMPLETED, FAILED)
    status_ne   ← กรองโดยไม่รวมสถานะที่ระบุ
    created_at  ← กรองตามวันที่ (YYYY-MM-DD) หรือทั้งเดือน (YYYY-MM)
    limit       ← จำนวนข้อมูลที่ต้องการ (ค่าเริ่มต้น 20)
    offset      ← จำนวนรายการที่ข้ามก่อนเริ่มดึงข้อมูล ใช้สำหรับ Pagination
    ```
    """
    try:
        created_at = created_at or _query_value(request, "?created_at")
        status_not_filter = _status_not_from_query(request, status_not or status_ne)
        created_at_from, created_at_to = _parse_created_at_filter(created_at)
        total = count_jobs(
            conn,
            status=status,
            status_not=status_not_filter,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
        )
        rows = get_all_jobs(
            conn,
            status=status,
            status_not=status_not_filter,
            limit=limit,
            offset=offset,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
        )
        jobs = [
            _make_job_record(row, get_items_by_job_id(conn, int(row["job_id"])))
            for row in rows
        ]
        return JobListResponse(
            total=total,
            limit=limit,
            offset=offset,
                        status_filter=status,
            status_not_filter=status_not_filter,
            created_at_filter=created_at,
            jobs=jobs,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")

# ============================================================================
# GET /jobs/{job_id}  — ดูรายละเอียด job
# ============================================================================

@router.get(
    "/jobs/{job_id}",
    tags=["Status"],
    summary="ดูรายละเอียด job ตาม job_id",
    response_model=JobRecord,
    response_description="ข้อมูล job ทั้งหมดรวม item_codes และ backup paths",
    responses={
        200: {
            "description": "ข้อมูล job",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": 20260714001,
                        "request_id": "b7a8f1b0-7df2-4c8e-9e4c-26070001",
                        "integration_profile": "RAGTAG",
                        "requested_by": "T9334",
                        "requested_at": "2026-07-08 10:00:00",
                        "source_system": "STM",
                        "status": "FAILED",
                        "error_message": "DTW batch failed",
                        "head_backup_path": "C:\\...\\bak_file\\20260708_100001_TF_Head.txt",
                        "detail_backup_path": "C:\\...\\bak_file\\20260708_100001_TF_Detail.txt",
                        "created_at": "2026-07-08 10:00:00",
                        "updated_at": "2026-07-08 10:00:16",
                        "items": [
                            {
                                "item_id": 1,
                                "line_num": 0,
                                "item_code": "TH0230226055401",
                                "quantity": "1",
                                "warehouse_code": "INTRAN",
                                "item_status": "PROCESSING",
                                "transfer_no": "Test_TF01",
                                "record_key": "1",
                                "created_at": "2026-07-08 10:00:01",
                            },
                            {
                                "item_id": 2,
                                "line_num": 1,
                                "item_code": "TH0230226066978",
                                "quantity": "1",
                                "warehouse_code": "INTRAN",
                                "item_status": "PROCESSING",
                                "transfer_no": "Test_TF01",
                                "record_key": "1",
                                "created_at": "2026-07-08 10:00:01",
                            },
                        ],
                    }
                }
            },
        },
        404: {"description": "ไม่พบ job_id นี้"},
        500: {"description": "DB connection failed"},
    },
)
async def get_job_detail(job_id: int, conn = Depends(get_db)) -> JobRecord:
    """ดูข้อมูลของ job ทั้งหมด รวมถึง item_code ทุกรายการและ backup file paths

    ใช้ endpoint นี้เพื่อ:
    - ตรวจสอบ status ของ job
    - ดู item_code ทุกตัวที่อยู่ใน job นี้
        - ดู error_message กรณีที่ล้มเหลว
    - ดู backup paths สำหรับใช้ resend
    """
    try:
        job = get_job_by_id(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        item_rows = get_items_by_job_id(conn, job_id)
        return _make_job_record(job, item_rows)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Internal Server Error")
