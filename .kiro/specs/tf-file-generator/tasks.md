# Implementation Plan: TF File Generator

## Overview

สร้าง FastAPI Web Service สำหรับรับ JSON Payload แล้วแปลงเป็นไฟล์ Tab-Delimited 2 ไฟล์ (`TF_Head.txt` และ `TF_Detail.txt`) โดยแบ่งการ implement ออกเป็น Layer ตามลำดับ ได้แก่ Configuration → Schema → File Writer → Service → API แล้วปิดด้วย Tests และ Manual Runner

---

## Tasks

- [ ] 1. ตั้งค่าโครงสร้างโปรเจกต์และ Dependencies
  - สร้างโฟลเดอร์ `tf-file-generator/` และ `tests/`
  - สร้างไฟล์ `requirements.txt` พร้อม dependencies ที่กำหนด (`fastapi>=0.111.0`, `uvicorn[standard]>=0.29.0`, `pydantic>=2.0.0`, `requests>=2.31.0`, `pytest>=8.0.0`, `httpx>=0.27.0`)
  - สร้าง placeholder files: `main.py`, `router.py`, `schemas.py`, `tf_service.py`, `file_writer.py`, `config.py`, `test_runner.py`, `tests/__init__.py`
  - _Requirements: Requirement 9, Requirement 10_

- [ ] 2. Implement Configuration Layer (`config.py`)
  - [ ] 2.1 สร้าง `config.py` กำหนดค่า `OUTPUT_DIR` เป็น `C:\tnl_appl\support_b1\Template`
    - Export ค่าคงที่ `OUTPUT_DIR: str` สำหรับให้ layer อื่นนำไปใช้
    - _Requirements: Requirement 9.1, Requirement 6.3_

- [ ] 3. Implement Schema Layer (`schemas.py`)
  - [ ] 3.1 สร้าง Pydantic models `TFHeadInput`, `TFDetailInput`, `TFPayload`, `GenerateResponse`
    - `TFHeadInput`: `RecordKey` required non-empty string, 16 optional fields default `""`
    - `TFDetailInput`: `RecordKey` required non-empty string, 16 optional fields default `""`
    - `TFPayload`: `head: TFHeadInput`, `details: List[TFDetailInput]` with `min_length=1`
    - `GenerateResponse`: `success: bool`, `message: str`, `files: List[str]`
    - _Requirements: Requirement 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, Requirement 8_

  - [ ]* 3.2 เขียน unit tests สำหรับ Schema Layer (`tests/test_schemas.py`)
    - ทดสอบ valid payload ครบถ้วน
    - ทดสอบ missing `RecordKey` ใน `TFHeadInput` → validation error
    - ทดสอบ empty string `RecordKey` ใน `TFHeadInput` → validation error
    - ทดสอบ missing `RecordKey` ใน `TFDetailInput` → validation error
    - ทดสอบ `details` เป็น empty list → validation error
    - ทดสอบ optional fields ที่ไม่ส่งมา → default เป็น `""`
    - _Requirements: Requirement 2.1–2.7, Requirement 10.1_

- [ ] 4. Implement File Writer Layer (`file_writer.py`)
  - [ ] 4.1 สร้าง class `FileWriter` พร้อม `__init__(self, output_dir: str)` และ `write_tab_file(self, filename: str, rows: List[List[str]]) -> str`
    - `__init__`: เก็บ `output_dir` เป็น instance variable
    - `write_tab_file`: สร้าง directory ด้วย `os.makedirs(..., exist_ok=True)`, เขียนไฟล์ด้วย tab separator + newline, encode UTF-8, คืน absolute path
    - _Requirements: Requirement 5.1–5.5, Requirement 6.1, 6.2, Requirement 9.2_

  - [ ]* 4.2 เขียน unit tests สำหรับ File Writer Layer (`tests/test_file_writer.py`)
    - ทดสอบ tab-delimited format ถูกต้อง (column คั่นด้วย `\t`)
    - ทดสอบ newline termination (`\n`) ท้ายทุก row
    - ทดสอบ UTF-8 encoding (ใช้ข้อความภาษาไทย)
    - ทดสอบ directory auto-creation ด้วย `tmp_path` fixture
    - ทดสอบ overwrite file เมื่อมีไฟล์เดิมอยู่
    - ทดสอบ return value เป็น absolute path
    - _Requirements: Requirement 5.1–5.5, Requirement 6.1–6.2, Requirement 10.3_

- [ ] 5. Checkpoint — ตรวจสอบ File Writer ทำงานถูกต้อง
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement Service Layer (`tf_service.py`)
  - [ ] 6.1 สร้าง class `TFService` พร้อม `generate_tf_files`, `_build_head_rows`, `_build_detail_rows`
    - `_build_head_rows(head: TFHeadInput) -> List[List[str]]`: คืน `[header_row, data_row]` ตาม canonical 17-column order ของ Head
    - `_build_detail_rows(details: List[TFDetailInput]) -> List[List[str]]`: คืน `[header_row, data_row_0, ..., data_row_N]` ตาม canonical 17-column order ของ Detail
    - `generate_tf_files(payload: TFPayload) -> GenerateResponse`: เรียก build rows, เรียก `FileWriter`, จัดการ `IOError` → raise `FileWriteException`, คืน `GenerateResponse`
    - สร้าง `FileWriteException` exception class ใน module เดียวกันหรือแยก file
    - _Requirements: Requirement 3.1–3.5, Requirement 4.1–4.6, Requirement 7.1, 7.4, Requirement 8.1–8.3_

  - [ ]* 6.2 เขียน unit tests สำหรับ Service Layer (`tests/test_tf_service.py`)
    - ทดสอบ `_build_head_rows` คืน 2 rows เสมอ
    - ทดสอบ `_build_head_rows` header row มี 17 columns ตาม canonical order
    - ทดสอบ `_build_head_rows` data row ค่าตรงกับ input ทุก field
    - ทดสอบ `_build_head_rows` None/omitted field → `""` ใน data row
    - ทดสอบ `_build_detail_rows` คืน `1 + N` rows เมื่อส่ง N details
    - ทดสอบ `_build_detail_rows` header row มี 17 columns ตาม canonical order
    - ทดสอบ `_build_detail_rows` รักษาลำดับ rows ตรงกับ input list
    - ทดสอบ `generate_tf_files` เรียก `FileWriter.write_tab_file` 2 ครั้ง (mock FileWriter)
    - ทดสอบ `generate_tf_files` raise `FileWriteException` เมื่อ `write_tab_file` raise `IOError`
    - _Requirements: Requirement 3.2–3.5, Requirement 4.2–4.6, Requirement 7.1, Requirement 10.2_

- [ ] 7. Implement API Layer (`router.py` และ `main.py`)
  - [ ] 7.1 สร้าง `router.py` กำหนด POST `/generate-tf` endpoint
    - Inject `TFPayload` ผ่าน FastAPI request body
    - เรียก `TFService.generate_tf_files(payload)`
    - Handle `FileWriteException` → return `HTTPException(status_code=500, detail=...)`
    - Return `GenerateResponse` พร้อม HTTP 200 เมื่อสำเร็จ
    - _Requirements: Requirement 1.1–1.4, Requirement 7.2–7.3_

  - [ ] 7.2 สร้าง `main.py` เป็น FastAPI app entry point
    - สร้าง `FastAPI()` instance
    - Include router จาก `router.py`
    - _Requirements: Requirement 1.1_

- [ ] 8. สร้าง Manual Test Runner (`test_runner.py`)
  - [ ] 8.1 สร้าง `test_runner.py` ส่ง real HTTP POST request ไปยัง running server
    - ใช้ `requests` library ส่ง payload ตัวอย่างจาก design document
    - Print response status code และ JSON body
    - _Requirements: Requirement 10.5_

- [ ] 9. เขียน Integration Tests (`tests/test_api.py`)
  - [ ] 9.1 เขียน integration tests ด้วย FastAPI `TestClient`
    - Setup: override `OUTPUT_DIR` ด้วย `tmp_path` fixture
    - ทดสอบ POST `/generate-tf` ด้วย valid payload → HTTP 200 + `GenerateResponse`
    - ทดสอบ `TF_Head.txt` และ `TF_Detail.txt` ถูกสร้างใน output directory
    - ทดสอบ content ของไฟล์: header row ถูกต้อง, จำนวน data rows ถูกต้อง
    - ทดสอบ POST `/generate-tf` ด้วย payload ที่ขาด `RecordKey` → HTTP 422
    - ทดสอบ POST `/generate-tf` ด้วย `details` empty list → HTTP 422
    - _Requirements: Requirement 1.2–1.3, Requirement 10.4_

- [ ] 10. Final Checkpoint — ตรวจสอบ tests ทั้งหมดผ่าน
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks ที่ marked ด้วย `*` เป็น optional สามารถข้ามได้หากต้องการ MVP เร็ว
- แต่ละ task อ้างอิง Requirement เฉพาะเจาะจงเพื่อ traceability
- Checkpoints (task 5, 10) ช่วยยืนยัน correctness ในแต่ละ phase
- Unit tests ควรใช้ `tmp_path` fixture ของ pytest เพื่อหลีกเลี่ยงการเขียนไฟล์จริงบน disk
- `FileWriteException` ควร subclass `Exception` เพื่อให้ catch แยกจาก general exception ได้ชัดเจน

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1"] },
    { "id": 3, "tasks": ["4.2", "6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "8.1"] },
    { "id": 6, "tasks": ["9.1"] }
  ]
}
```
