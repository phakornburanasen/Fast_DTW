# main.py - FastAPI application entry point
# Supports multi-worker mode on Windows via a shared listening socket.
from __future__ import annotations

import asyncio
import multiprocessing
import socket
import sys

from fastapi import FastAPI

from contextlib import asynccontextmanager

from queue_manager import start_worker
from router import router
from tf_service import TFService
from log_service import LogService


HOST = "0.0.0.0"
PORT = 60001
DEFAULT_WORKERS = 1

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background queue worker on application startup."""
    log_service = LogService()
    start_worker(app, TFService(log_service=log_service))
    yield
    # Cleanup task here if needed

app = FastAPI(
    title="TF File Generator",
    description="""
## TF File Generator API


ระบบสร้างและส่งไฟล์ Transfer (**TF_Head.txt**, **TF_Detail.txt**) เข้า SAP Business One ผ่าน DTW

---

### Endpoints

| Method | Path | คำอธิบาย |
|--------|------|-----------|
| `POST` | `/api/DTW_Service/generate-tf` | รับ payload, สร้างไฟล์ TF, รัน DTW |
| `GET`  | `/api/DTW_Service/status/item_code/{item_code}` | ดูสถานะตาม ItemCode |
| `GET`  | `/api/DTW_Service/jobs` | ดู job ทั้งหมด (filter status/status_ne/created_at + pagination) |
| `GET`  | `/api/DTW_Service/jobs/{job_id}` | ดูรายละเอียด job ตาม job_id |
| `POST` | `/api/DTW_Service/resend_job/item_code/{item_code}` | ทำงานซ้ำสำหรับ ItemCode ที่ยังไม่สำเร็จ |
| `POST` | `/api/DTW_Service/resend_job/request_id/{request_id}` | ทำงานซ้ำสำหรับ request_id ที่ยังไม่สำเร็จ |
| `POST` | `/api/DTW_Service/resend_job/job/{job_id}` | ทำงานซ้ำโดยระบุ internal tf_job_log.job_id |
| `POST` | `/api/DTW_Service/resend_job/job_no/{job_no}` | ทำงานซ้ำโดยระบุ tf_job_log.job_no รูปแบบ YYYYMMDD### |

### Job Identifiers

- `job_id` ใน `/resend_job/job/{job_id}` คือ internal `tf_job_log.job_id` ที่ใช้เชื่อมตารางลูก
- `job_no` ใน `/resend_job/job_no/{job_no}` คือเลขงานรูปแบบวันที่ เช่น `20260714001`
- response หลักของระบบยังแสดงเลขงานรูปแบบวันที่ใน field `job_id` เพื่อให้ผู้ใช้ติดตามได้ง่าย

---

### Job Status Flow

```
RECEIVED → PROCESSING → COMPLETED
                     ↘ FAILED
```

### Pipeline Steps (process_queued_job)

```
1. clear_temp    — ลบไฟล์เก่า
2. write_files   — เขียน TF_Head.txt + TF_Detail.txt
3. backup_files  — COPY ไป bak_file/ (ต้นฉบับยังอยู่สำหรับ DTW)
4. run_batch     — รัน call_dtw_use_xml.bat
```
""",
    version="1.0.0",
    contact={
        "name": "TF File Generator",
    },
    openapi_tags=[
        {
            "name": "Transfer File",
            "description": "สร้างและส่งไฟล์ TF เข้า DTW",
        },
        {
            "name": "Status",
            "description": "ตรวจสอบสถานะ job และ ItemCode",
        },
        {
            "name": "Resend",
            "description": "ทำงานซ้ำสำหรับ job ที่ล้มเหลว",
        },
    ],
    lifespan=lifespan
)

app.include_router(router)


def _run_worker(sock: socket.socket, workers: int) -> None:
    """Start one uvicorn server using the already-bound parent socket."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
        workers=workers,
    )
    server = uvicorn.Server(config)
    config.setup_event_loop()
    asyncio.run(server.serve(sockets=[sock]))


def main(workers: int = DEFAULT_WORKERS) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(1024)
    sock.set_inheritable(True)

    print(f"[tf_generator] Starting {workers} workers on http://{HOST}:{PORT}", flush=True)
    print("[tf_generator] Press Ctrl+C to stop all workers", flush=True)

    processes: list[multiprocessing.Process] = []
    for i in range(workers):
        process = multiprocessing.Process(
            target=_run_worker,
            args=(sock, workers),
            name=f"worker-{i + 1}",
            daemon=True,
        )
        process.start()
        print(f"[tf_generator] Worker {i + 1} started (pid={process.pid})", flush=True)
        processes.append(process)

    sock.close()

    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n[tf_generator] Shutting down workers...", flush=True)
        for process in processes:
            process.terminate()
        for process in processes:
            process.join()
        print("[tf_generator] All workers stopped.", flush=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--multiprocessing-fork" not in sys.argv:
        main()
