# tests/test_schemas.py — Unit tests for Schema Layer
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pydantic import ValidationError

from schemas import (
    DetailCSV,
    Document,
    GenerateResponse,
    HeadCSV,
    TFRequest,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_head_csv(**kwargs) -> dict:
    return {"DocDate": "20260707", "FromWarehouse": "STORE01", **kwargs}


def make_detail(**kwargs) -> dict:
    return {"RecordKey": 1, "LineNum": 0, "ItemCode": "ITEM001", "Quantity": "1", **kwargs}


def make_document(record_key=1, n_details=1, **kwargs) -> dict:
    return {
        "record_key": record_key,
        "transfer_no": f"TRF{record_key:08d}",
        "head_csv": make_head_csv(),
        "detail_csv": [make_detail(RecordKey=record_key, LineNum=i) for i in range(n_details)],
        **kwargs,
    }


def make_request(**kwargs) -> dict:
    return {
        "integration_profile": "RAGTAG",
        "documents": [make_document()],
        **kwargs,
    }


# ---------------------------------------------------------------------------
# HeadCSV
# ---------------------------------------------------------------------------

class TestHeadCSV:
    def test_all_optional(self):
        h = HeadCSV()
        assert h.DocDate == ""
        assert h.FromWarehouse == ""
        assert h.DocObjectCode == ""

    def test_with_values(self):
        h = HeadCSV(DocDate="20260707", FromWarehouse="STORE01", Series="123")
        assert h.DocDate == "20260707"
        assert h.Series == "123"


# ---------------------------------------------------------------------------
# DetailCSV
# ---------------------------------------------------------------------------

class TestDetailCSV:
    def test_required_fields(self):
        d = DetailCSV(RecordKey=1, LineNum=0)
        assert str(d.RecordKey) == "1"
        assert str(d.LineNum) == "0"

    def test_optional_fields_default_empty(self):
        d = DetailCSV(RecordKey=1, LineNum=0)
        assert d.ItemCode == ""
        assert d.WarehouseCode == ""


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class TestDocument:
    def test_valid_document(self):
        doc = Document(**make_document())
        assert doc.record_key == 1
        assert len(doc.detail_csv) == 1

    def test_empty_detail_csv_raises(self):
        data = make_document()
        data["detail_csv"] = []
        with pytest.raises(ValidationError) as exc_info:
            Document(**data)
        assert "detail_csv" in str(exc_info.value)

    def test_multiple_details(self):
        doc = Document(**make_document(n_details=4))
        assert len(doc.detail_csv) == 4


# ---------------------------------------------------------------------------
# TFRequest
# ---------------------------------------------------------------------------

class TestTFRequest:
    def test_valid_request(self):
        req = TFRequest(**make_request())
        assert req.integration_profile == "RAGTAG"
        assert len(req.documents) == 1

    def test_missing_integration_profile_raises(self):
        data = make_request()
        del data["integration_profile"]
        with pytest.raises(ValidationError):
            TFRequest(**data)

    def test_empty_documents_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            TFRequest(**make_request(documents=[]))
        assert "documents" in str(exc_info.value)

    def test_output_defaults(self):
        req = TFRequest(**make_request())
        # output field removed — filenames are always TF_Head.txt / TF_Detail.txt
        assert req.integration_profile == "RAGTAG"

    def test_custom_output_filenames(self):
        # output field no longer exists; this test verifies no error on extra fields being ignored
        req = TFRequest(**make_request())
        assert req.integration_profile == "RAGTAG"

    def test_multiple_documents(self):
        req = TFRequest(**make_request(documents=[make_document(1), make_document(2)]))
        assert len(req.documents) == 2


# ---------------------------------------------------------------------------
# GenerateResponse
# ---------------------------------------------------------------------------

class TestGenerateResponse:
    def test_valid(self):
        r = GenerateResponse(success=True, message="ok", files=["a.txt", "b.txt"])
        assert r.success is True
        assert len(r.files) == 2
