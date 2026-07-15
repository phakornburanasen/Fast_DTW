# TF File Generator - Improvement Roadmap & Plan

## Phase 1: Critical Bug Fixes & Stabilization (Immediate)
**เป้าหมาย:** ระบบต้องไม่สูญเสียข้อมูล และแก้ปัญหา Concurrency

1.  **เปลี่ยนให้รัน `workers=1`**
    *   **ไฟล์:** `main.py`
    *   **แก้:** ปรับ Default worker จาก 4 เหลือ 1 เพื่อให้ Queue ทำงานแบบ Sequential ไม่แย่ง Lock กันที่ in-memory level ก่อนที่ระบบคิวจริงจะพร้อม
2.  **เอา Hardcode Secrets ออก**
    *   **ไฟล์:** `config.py`
    *   **แก้:** เอา `Thanulux2569` ออก และเปลี่ยนไปใช้ `pydantic-settings` ร่วมกับไฟล์ `.env`
3.  **แก้ Exception 500 Information Disclosure**
    *   **ไฟล์:** `router.py`
    *   **แก้:** ซ่อนรายละเอียด SQL Error เวลา Exception เด้งกลับไปที่ Client เปลี่ยนให้แสดง "Internal Server Error" และเก็บ Error ตัวจริงไว้ที่ Log file
4.  **Refactor FastAPI Database Dependencies**
    *   **ไฟล์:** `router.py`
    *   **แก้:** นำ `get_connection()` และกระบวนการ close ไปผูกกับ `FastAPI Depends()` ให้เกิดเป็น Dependency Injection อย่างแท้จริง ช่วยลด Duplicate Code ทุก Endpoint ลงได้มาก

## Phase 2: Structural Refactoring (1-2 Weeks)
**เป้าหมาย:** วางสถาปัตยกรรมรองรับ Scale และ Test

1.  **เปลี่ยน Threading Lock เป็น File Lock**
    *   **ไฟล์:** `batch_runner.py`
    *   **แก้:** ใช้ Library `filelock` ทำ System-wide lock หากอนาคตต้องขยาย Worker ระบบไฟล์ Temp จะไม่ชนกันเวลา Process แยกกันรัน
2.  **Dependency Injection (DI) Service Layer**
    *   **ไฟล์:** `tf_service.py`
    *   **แก้:** เปลี่ยนวิธีการเรียกใช้ LogService ภายใน `__init__` ให้รับ Object เข้ามาผ่าน Constructor ทำให้ตอนเขียน Test สามารถ Mock Object LogService ได้สะดวก 
3.  **เปลี่ยน FastAPI Event Listener เป็น Lifespan**
    *   **ไฟล์:** `main.py`
    *   **แก้:** ลบ `@app.on_event("startup")` ซึ่งถูก Deprecate และเปลี่ยนเป็นโครงสร้าง `@asynccontextmanager def lifespan(app: FastAPI)` ตามมาตรฐาน FastAPI รุ่นใหม่ 
4.  **เพิ่ม Unit Tests เบื้องต้น**
    *   **ไฟล์:** `tests/test_tf_service.py` 
    *   **แก้:** เขียนเทสเพื่อตรวจสอบ Format ของ `_build_head_rows` และ `_build_detail_rows` 

## Phase 3: Resilience & Recovery (2-3 Weeks)
**เป้าหมาย:** ระบบต้องฟื้นฟูตัวเองได้ หาก SAP หรือ Database ล้ม 

1.  **Centralized Queuing (Database-backed)**
    *   **ไฟล์:** สร้างไฟล์ใหม่เช่น `db/queue_repository.py`
    *   **แก้:** เลิกใช้ `asyncio.Queue` แบบ In-memory และใช้ `tf_job_log` (ที่ status เป็น RECEIVED) มาทำหน้าที่คิวแทน โดยให้ Worker วนลูปอ่าน Database แล้ว Lock Row ขึ้นมาทำงาน
2.  **เพิ่ม Retry Mechanism**
    *   **ไฟล์:** `tf_service.py` / `batch_runner.py`
    *   **แก้:** เพิ่มไลบรารี `tenacity` เข้ามารันซ้ำกรณี Network timeout หรือ Database Connection Failed แบบชั่วคราว
3.  **เพิ่มระบบ Alerting เบื้องต้น**
    *   สร้างระบบแจ้งเตือนกรณี Job `FAILED` หรือ DTW Timeout เพื่อส่ง Notification เข้า Email หรือ Webhook (Line Notify/Teams)

## Phase 4: Production Enterprise Readiness (Future)
**เป้าหมาย:** เตรียมระบบรองรับ High-Availability และ Logging แบบศูนย์รวม 

1.  **ใช้ External Broker & Worker Model**
    *   เปลี่ยนจากการใช้ Database-backed queue ไปเป็น Redis + Celery / ARQ (ถ้า Load เริ่มหนักระดับร้อย Job ต่อนาที)
2.  **Centralized Logging Platform**
    *   รวม Log ทั้งหมด (รวมถึง DTW Log ที่สร้างไว้ใน `logs/dtw_jobs/`) ยิงส่งไปที่ ELK Stack (Elasticsearch, Logstash, Kibana) หรือ Grafana Loki เพื่อดูกราฟปัญหา
3.  **Load Test & Stress Test**
    *   ใช้ `locust` มาจำลองยิง Request เข้า 1,000 requests ต่อวินาที ดูการตอบสนองของ DTW Batch Process ว่ารับได้ถึงลิมิตตรงไหน