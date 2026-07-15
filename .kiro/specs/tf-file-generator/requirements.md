# Requirements Document

## Introduction

ระบบ TF File Generator คือ FastAPI Web Service ที่รับ JSON Payload แล้วแปลงและสร้างไฟล์ข้อความแบบ Tab-Delimited 2 ไฟล์ ได้แก่ `TF_Head.txt` และ `TF_Detail.txt` บันทึกลงในโฟลเดอร์ `C:\tnl_appl\support_b1\Template` ระบบออกแบบโดยแบ่งความรับผิดชอบเป็น 4 Layer ชัดเจน ได้แก่ API Layer, Schema Layer, Service Layer และ File Writer Layer เพื่อให้ง่ายต่อการดูแลรักษาและทดสอบ

---

## Glossary

- **API_Layer**: ส่วนที่รับ HTTP Request และส่ง HTTP Response ประกอบด้วย `main.py` และ `router.py`
- **Schema_Layer**: ส่วนที่กำหนดโครงสร้างข้อมูล (Pydantic models) ใน `schemas.py`
- **Service_Layer**: ส่วนที่ประมวลผล business logic ใน `tf_service.py`
- **File_Writer**: ส่วนที่รับผิดชอบการเขียนไฟล์ Tab-Delimited ใน `file_writer.py`
- **TFPayload**: JSON Request Body ที่มี `head` (TFHeadInput) และ `details` (list of TFDetailInput)
- **TFHeadInput**: Pydantic model แทนข้อมูล Header ของเอกสาร มี 17 columns
- **TFDetailInput**: Pydantic model แทนข้อมูล Detail line ของเอกสาร มี 17 columns
- **GenerateResponse**: Pydantic model แทน HTTP Response ประกอบด้วย `success`, `message`, `files`
- **RecordKey**: Field บังคับใน TFHeadInput และ TFDetailInput ต้องไม่เป็นค่าว่าง
- **Tab_Delimited_File**: ไฟล์ข้อความที่แต่ละ column คั่นด้วย `\t` และแต่ละ row จบด้วย `\n`
- **Output_Directory**: โฟลเดอร์ปลายทางสำหรับบันทึกไฟล์ กำหนดใน `config.py` ค่าเริ่มต้น `C:\tnl_appl\support_b1\Template`
- **FileWriteException**: Exception ที่ Service_Layer ยกขึ้นเมื่อเกิดข้อผิดพลาดในการเขียนไฟล์
- **Header_Row**: แถวแรกในไฟล์ Tab-Delimited ที่ระบุชื่อ column ตามลำดับที่กำหนด
- **Data_Row**: แถวที่มีค่าข้อมูลจริงในไฟล์ Tab-Delimited

---

## Requirements

### Requirement 1: API Endpoint

**User Story:** As a client application, I want to call a single HTTP endpoint with a JSON payload, so that I can trigger the generation of TF files without complex integration.

#### Acceptance Criteria

1. THE API_Layer SHALL expose an HTTP POST endpoint at path `/generate-tf`
2. WHEN a valid TFPayload is received at `/generate-tf`, THE API_Layer SHALL return an HTTP 200 response with a GenerateResponse JSON body
3. WHEN the request body cannot be parsed as valid JSON, THE API_Layer SHALL return an HTTP 422 Unprocessable Entity response with Pydantic validation error details
4. WHEN the Service_Layer raises a FileWriteException, THE API_Layer SHALL return an HTTP 500 response with a JSON body containing a `detail` field describing the error

---

### Requirement 2: Request Payload Validation

**User Story:** As a developer, I want the system to validate all incoming payloads before processing, so that only well-formed data reaches the file generation logic.

#### Acceptance Criteria

1. THE Schema_Layer SHALL define TFPayload as a Pydantic model containing a required `head` field of type TFHeadInput and a required `details` field of type list with at least 1 TFDetailInput
2. THE Schema_Layer SHALL define TFHeadInput with `RecordKey` as a required non-empty string field and 16 optional string fields each defaulting to empty string
3. THE Schema_Layer SHALL define TFDetailInput with `RecordKey` as a required non-empty string field and 16 optional string fields each defaulting to empty string
4. WHEN TFPayload is provided with `details` as an empty list, THE Schema_Layer SHALL reject it and return a validation error
5. WHEN TFHeadInput is provided without `RecordKey` or with `RecordKey` as an empty string, THE Schema_Layer SHALL reject it and return a validation error
6. WHEN TFDetailInput is provided without `RecordKey` or with `RecordKey` as an empty string, THE Schema_Layer SHALL reject it and return a validation error
7. WHEN optional fields are omitted from TFHeadInput or TFDetailInput, THE Schema_Layer SHALL assign empty string as the default value for each omitted field

---

### Requirement 3: TF_Head.txt File Generation

**User Story:** As a business user, I want the system to generate a correctly formatted TF_Head.txt file, so that downstream systems can import the header data without manual reformatting.

#### Acceptance Criteria

1. WHEN generate_tf_files is called with a valid TFPayload, THE Service_Layer SHALL produce a TF_Head.txt file in the Output_Directory
2. THE Service_Layer SHALL produce TF_Head.txt containing exactly 2 rows: one Header_Row and one Data_Row
3. THE Service_Layer SHALL produce a Header_Row in TF_Head.txt with exactly 17 column names in the following canonical order: `RecordKey`, `DocEntry`, `Address`, `CardCode`, `CardName`, `Comments`, `ContactPerson`, `DocDate`, `FromWarehouse`, `JournalMemo`, `PriceList`, `Reference1`, `Reference2`, `SalesPersonCode`, `Series`, `TaxDate`, `DocObjectCode`
4. THE Service_Layer SHALL produce a Data_Row in TF_Head.txt where each value corresponds to the matching field in TFHeadInput, in the same canonical column order as the Header_Row
5. WHEN a TFHeadInput field value is None or not provided, THE Service_Layer SHALL write an empty string for that column in the Data_Row

---

### Requirement 4: TF_Detail.txt File Generation

**User Story:** As a business user, I want the system to generate a correctly formatted TF_Detail.txt file, so that all line-item detail data is captured for downstream processing.

#### Acceptance Criteria

1. WHEN generate_tf_files is called with a valid TFPayload, THE Service_Layer SHALL produce a TF_Detail.txt file in the Output_Directory
2. THE Service_Layer SHALL produce TF_Detail.txt containing exactly `1 + N` rows where N equals the number of TFDetailInput items in `payload.details`
3. THE Service_Layer SHALL produce a Header_Row in TF_Detail.txt with exactly 17 column names in the following canonical order: `RecordKey`, `LineNum`, `Currency`, `DiscountPercent`, `Factor2`, `Factor3`, `Factor4`, `Factor`, `ItemCode`, `ItemDescription`, `Price`, `ProjectCode`, `Quantity`, `Rate`, `SerialNumber`, `VendorNum`, `WarehouseCode`
4. THE Service_Layer SHALL produce one Data_Row per TFDetailInput item where each value corresponds to the matching field in that TFDetailInput, in the same canonical column order as the Header_Row
5. WHEN a TFDetailInput field value is None or not provided, THE Service_Layer SHALL write an empty string for that column in the corresponding Data_Row
6. THE Service_Layer SHALL preserve the order of Data_Rows in TF_Detail.txt to match the order of TFDetailInput items as received in `payload.details`

---

### Requirement 5: Tab-Delimited File Format

**User Story:** As an integration engineer, I want both output files to follow a strict Tab-Delimited format with UTF-8 encoding, so that downstream systems can reliably parse the files without encoding or delimiter issues.

#### Acceptance Criteria

1. THE File_Writer SHALL write each row by joining all column values with a tab character (`\t`) as the delimiter
2. THE File_Writer SHALL terminate each row with a newline character (`\n`)
3. THE File_Writer SHALL encode all written files using UTF-8
4. THE File_Writer SHALL create or overwrite the file at `{Output_Directory}/{filename}` on each invocation
5. THE File_Writer SHALL return the absolute file path of the written file as a string

---

### Requirement 6: Output Directory Management

**User Story:** As a system administrator, I want the output directory to be automatically created if it does not exist, so that the system can operate without requiring manual directory setup.

#### Acceptance Criteria

1. THE File_Writer SHALL create the Output_Directory and all necessary parent directories if they do not already exist before writing any file
2. WHEN the Output_Directory already exists, THE File_Writer SHALL proceed with file writing without raising an error
3. THE API_Layer SHALL read the Output_Directory path exclusively from `config.py` and SHALL NOT accept directory paths from the client request

---

### Requirement 7: Error Handling

**User Story:** As a client application, I want clear and consistent error responses, so that I can identify and resolve issues quickly without guessing what went wrong.

#### Acceptance Criteria

1. WHEN an IOError or OSError occurs during file writing, THE Service_Layer SHALL raise a FileWriteException with a descriptive message containing the original error detail
2. WHEN a FileWriteException is raised, THE API_Layer SHALL respond with HTTP 500 and a JSON body `{ "detail": "<error message>" }`
3. WHEN a Pydantic validation error occurs, THE API_Layer SHALL respond with HTTP 422 and the standard Pydantic error detail body
4. IF a file write operation fails after writing TF_Head.txt but before completing TF_Detail.txt, THEN THE Service_Layer SHALL propagate the FileWriteException and SHALL NOT leave the caller with a false success response

---

### Requirement 8: Successful Response

**User Story:** As a client application, I want a structured success response that includes the paths of the generated files, so that I can confirm what was created and where.

#### Acceptance Criteria

1. WHEN both TF_Head.txt and TF_Detail.txt are written successfully, THE Service_Layer SHALL return a GenerateResponse with `success` set to `True`
2. WHEN both files are written successfully, THE Service_Layer SHALL return a GenerateResponse with `message` set to a non-empty string describing the outcome
3. WHEN both files are written successfully, THE Service_Layer SHALL return a GenerateResponse with `files` containing the absolute paths of both TF_Head.txt and TF_Detail.txt

---

### Requirement 9: Configuration

**User Story:** As a system administrator, I want all deployment-specific settings to be centralized in a single configuration file, so that I can change the output path without modifying business logic code.

#### Acceptance Criteria

1. THE API_Layer SHALL load the Output_Directory path from `config.py` at application startup
2. THE File_Writer SHALL accept the Output_Directory as a constructor parameter so that it can be overridden in tests without modifying configuration files

---

### Requirement 10: Testing

**User Story:** As a developer, I want a comprehensive test suite covering all components, so that I can verify correctness and prevent regressions.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests for Schema_Layer validation covering valid payloads, missing required fields, and empty details list
2. THE test suite SHALL include unit tests for Service_Layer covering `_build_head_rows` column order, `_build_detail_rows` column order and row count, and default value handling
3. THE test suite SHALL include unit tests for File_Writer covering tab-delimited format, UTF-8 encoding, newline termination, and directory auto-creation using a temporary directory
4. THE test suite SHALL include integration tests using FastAPI TestClient that POST a valid payload to `/generate-tf` and verify HTTP 200 response and correct file content
5. THE test suite SHALL include a manual test runner script (`test_runner.py`) that sends a real HTTP POST request to a running server and prints the response status and body
