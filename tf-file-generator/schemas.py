# schemas.py — Pydantic request/response models
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# head_csv — one per document
# ---------------------------------------------------------------------------

class HeadCSV(BaseModel):
    """17-column head record. RecordKey and DocEntry are injected from the document."""
    DocEntry: str = ""
    Address: str = ""
    CardCode: str = ""
    CardName: str = ""
    Comments: str = ""
    ContactPerson: str = ""
    DocDate: str = ""
    FromWarehouse: str = ""
    JournalMemo: str = ""
    PriceList: str = ""
    Reference1: str = ""
    Reference2: str = ""
    SalesPersonCode: str = ""
    Series: str = ""
    TaxDate: str = ""
    DocObjectCode: str = ""


# ---------------------------------------------------------------------------
# detail_csv — many per document
# ---------------------------------------------------------------------------

class DetailCSV(BaseModel):
    """17-column detail record. RecordKey and LineNum position are injected."""
    RecordKey: Any  # int or str — will be cast to str
    LineNum: Any    # int or str — will be cast to str
    Currency: str = ""
    DiscountPercent: str = ""
    Factor2: str = ""
    Factor3: str = ""
    Factor4: str = ""
    Factor: str = ""
    ItemCode: str = ""
    ItemDescription: str = ""
    Price: str = ""
    ProjectCode: str = ""
    Quantity: str = ""
    Rate: str = ""
    SerialNumber: str = ""
    VendorNum: str = ""
    WarehouseCode: str = ""


# ---------------------------------------------------------------------------
# Document — one transfer order
# ---------------------------------------------------------------------------

class Document(BaseModel):
    record_key: Any  # int or str
    transfer_no: str = ""
    doc_date: str = ""
    series_name: str = ""
    series: str = ""
    from_shop_code: str = ""
    from_shop_name: str = ""
    to_shop_code: str = ""
    to_shop_name: str = ""
    from_whscode: str = ""
    status: str = ""
    print_out_date: str = ""
    create_by: str = ""
    total_qty: Optional[float] = None
    total_amount: Optional[float] = None
    head_csv: HeadCSV
    detail_csv: List[DetailCSV]

    @field_validator("detail_csv")
    @classmethod
    def detail_not_empty(cls, v: List[DetailCSV]) -> List[DetailCSV]:
        if len(v) == 0:
            raise ValueError("detail_csv must contain at least one item")
        return v


# ---------------------------------------------------------------------------
# Top-level request payload
# ---------------------------------------------------------------------------

class TFRequest(BaseModel):
    request_id: str = ""
    integration_profile: str  # used as RecordKey marker (e.g. "RAGTAG")
    side: str = ""
    requested_by: str = ""
    requested_at: str = ""
    source_system: str = ""
    documents: List[Document]

    @field_validator("documents")
    @classmethod
    def documents_not_empty(cls, v: List[Document]) -> List[Document]:
        if len(v) == 0:
            raise ValueError("documents must contain at least one item")
        return v


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class StepStatus(BaseModel):
    """Status of a single processing step."""
    step: str
    success: bool
    message: str
    detail: Optional[str] = None


class GenerateResponse(BaseModel):
    """Full response returned to the frontend after the entire pipeline."""
    success: bool
    message: str
    job_id: Optional[int] = None
    status: Optional[str] = None
    request_id: Optional[str] = None
    completed_at: Optional[str] = None
    request_by: Optional[str] = None
    files: List[str]
    steps: List[StepStatus] = []
    backup_files: List[str] = []


# ---------------------------------------------------------------------------
# Status API models
# ---------------------------------------------------------------------------

class ItemStatusRecord(BaseModel):
    job_id: int
    item_code: str
    line_num: int
    quantity: str
    warehouse_code: str
    item_status: str
    transfer_no: str
    doc_date: str
    from_warehouse: str
    request_id: str
    job_status: str
    requested_at: str
    created_at: str


class ItemStatusResponse(BaseModel):
    item_code: str
    records: List[ItemStatusRecord]
    total: int


# ---------------------------------------------------------------------------
# Resend API models
# ---------------------------------------------------------------------------

class ResendResponse(BaseModel):
    """Response returned after a resend (retry) operation."""
    success: bool
    message: str
    job_id: int
    status: str
    steps: List[StepStatus] = []


# ---------------------------------------------------------------------------
# Job list API models
# ---------------------------------------------------------------------------

class JobRecord(BaseModel):
    """Summary of a single job row."""
    job_id: int
    request_id: str
    integration_profile: str
    requested_by: str
    requested_at: str
    source_system: str
    status: str
    error_message: Optional[str] = None
    head_backup_path: Optional[str] = None
    detail_backup_path: Optional[str] = None
    created_at: str
    updated_at: str
    items: List["JobItemRecord"] = []


class JobItemRecord(BaseModel):
    """One item/detail line inside a job."""
    item_id: int
    line_num: int
    item_code: str
    quantity: str
    warehouse_code: str
    item_status: str
    transfer_no: str
    record_key: str
    created_at: str


JobRecord.model_rebuild()  # resolve forward-ref for items field


class JobListResponse(BaseModel):
    """Paginated list of jobs."""
    total: int
    limit: int
    offset: int
    status_filter: Optional[str] = None
    status_not_filter: Optional[str] = None
    created_at_filter: Optional[str] = None
    jobs: List[JobRecord]
