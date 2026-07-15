# tests/test_api.py — Integration tests using FastAPI TestClient
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tf_service
import router as router_module
from main import app
from tf_service import _DETAIL_COLUMNS, _HEAD_COLUMNS

client = TestClient(app)

# ---------------------------------------------------------------------------
# Sample payload (real-world format)
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "request_id": "test-001",
    "integration_profile": "RAGTAG",
    "side": "TFOUT",
    "requested_by": "T9334",
    "requested_at": "2026-07-07 15:10:00",
    "source_system": "STM",
    "documents": [
        {
            "record_key": 1,
            "transfer_no": "TRF26070001",
            "head_csv": {
                "Comments": "TRF26070001",
                "DocDate": "20260707",
                "FromWarehouse": "STORE01",
                "JournalMemo": "Transfer for ใบเกลี่ยโอน",
                "PriceList": "2",
                "Series": "123",
                "DocObjectCode": "67",
            },
            "detail_csv": [
                {"RecordKey": 1, "LineNum": 0, "ItemCode": "TH0100826058770", "Quantity": "1", "WarehouseCode": "INTRAN"},
                {"RecordKey": 1, "LineNum": 1, "ItemCode": "TH0100826058771", "Quantity": "1", "WarehouseCode": "INTRAN"},
            ],
        },
        {
            "record_key": 2,
            "transfer_no": "TRF26070002",
            "head_csv": {
                "Comments": "TRF26070002",
                "DocDate": "20260707",
                "FromWarehouse": "STORE03",
                "JournalMemo": "Transfer for ใบเกลี่ยโอน",
                "PriceList": "2",
                "Series": "123",
                "DocObjectCode": "67",
            },
            "detail_csv": [
                {"RecordKey": 2, "LineNum": 0, "ItemCode": "TH2508000013908", "Quantity": "1", "WarehouseCode": "INTRAN"},
            ],
        },
    ],
}

FAKE_JOB_ID = 20260714001


# ---------------------------------------------------------------------------
# Fixture: mock DB + batch runner, redirect output to tmp dir
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def override_output_dir(tmp_path, monkeypatch):
    # Prevent real subprocess calls in all service tests.
    monkeypatch.setattr(tf_service, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr("tf_service.run_dtw_batch",
                        lambda **kw: {"started": True, "wait_seconds": 15, "pid": 99999})

    # Patch LogService so it doesn't attempt a real DB connection.
    mock_log = MagicMock()
    mock_log.log_received.return_value = FAKE_JOB_ID
    monkeypatch.setattr(router_module, "_log_service", mock_log)

    # Replace the service with one pointing at tmp_path.
    new_service = tf_service.TFService(output_dir=str(tmp_path))
    monkeypatch.setattr(router_module, "_service", new_service)

    yield tmp_path


@pytest.fixture
def fake_db_dependency():
    """Provide a fake DB dependency for endpoints that normally open pyodbc."""
    app.dependency_overrides[router_module.get_db] = lambda: object()
    yield
    app.dependency_overrides.pop(router_module.get_db, None)


def make_job_row(job_id=FAKE_JOB_ID, status="COMPLETED"):
    return {
        "job_id": job_id,
        "request_id": "req-001",
        "integration_profile": "RAGTAG",
        "requested_by": "T9334",
        "requested_at": "2026-07-10 09:00:00",
        "source_system": "STM",
        "status": status,
        "error_message": None,
        "head_backup_path": r"C:\bak\TF_Head.txt",
        "detail_backup_path": r"C:\bak\TF_Detail.txt",
        "created_at": "2026-07-10 09:01:00",
        "updated_at": "2026-07-10 09:02:00",
    }


def make_job_item_row():
    return {
        "item_id": 1,
        "line_num": 0,
        "item_code": "TH0230226055401",
        "quantity": "1",
        "warehouse_code": "INTRAN",
        "item_status": "PROCESSING",
        "transfer_no": "TRF26070001",
        "record_key": "1",
        "created_at": "2026-07-10 09:01:00",
    }


# ---------------------------------------------------------------------------
# Happy path — POST /generate-tf now returns a queued acknowledgement
# ---------------------------------------------------------------------------

class TestGenerateTfEndpoint:
    def test_returns_200(self, override_output_dir):
        assert client.post("/generate-tf", json=VALID_PAYLOAD).status_code == 200

    def test_response_structure(self, override_output_dir):
        body = client.post("/generate-tf", json=VALID_PAYLOAD).json()
        assert body["success"] is True
        assert body["message"] == "Pipeline completed successfully"
        assert "job_id" in body
        assert body["status"] == "COMPLETED"
        assert body["request_id"] == VALID_PAYLOAD["request_id"]
        assert body["request_by"] == VALID_PAYLOAD["requested_by"]
        assert body["completed_at"]
        assert "steps" in body
        assert any(step["step"] == "4_run_batch" for step in body["steps"])

    def test_job_id_returned(self, override_output_dir):
        body = client.post("/generate-tf", json=VALID_PAYLOAD).json()
        assert isinstance(body["job_id"], int)
        assert body["job_id"] == FAKE_JOB_ID

    def test_log_received_called(self, override_output_dir):
        client.post("/generate-tf", json=VALID_PAYLOAD)
        router_module._log_service.log_received.assert_called_once()


# ---------------------------------------------------------------------------
# Validation errors — unchanged; payload validation still returns 422
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_missing_integration_profile_returns_422(self, override_output_dir):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "integration_profile"}
        assert client.post("/generate-tf", json=payload).status_code == 422

    def test_empty_documents_returns_422(self, override_output_dir):
        assert client.post("/generate-tf", json={**VALID_PAYLOAD, "documents": []}).status_code == 422

    def test_empty_detail_csv_returns_422(self, override_output_dir):
        payload = {**VALID_PAYLOAD, "documents": [{
            **VALID_PAYLOAD["documents"][0],
            "detail_csv": []
        }]}
        assert client.post("/generate-tf", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# Jobs — GET /jobs filters
# ---------------------------------------------------------------------------

class TestListJobsEndpoint:
    def test_filters_by_created_at_day(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        count_jobs = MagicMock(return_value=1)
        get_all_jobs = MagicMock(return_value=[make_job_row(status="FAILED")])
        get_items_by_job_id = MagicMock(return_value=[make_job_item_row()])
        monkeypatch.setattr(router_module, "count_jobs", count_jobs)
        monkeypatch.setattr(router_module, "get_all_jobs", get_all_jobs)
        monkeypatch.setattr(router_module, "get_items_by_job_id", get_items_by_job_id)

        response = client.get("/jobs?status=FAILED&created_at=2026-07-10&limit=10&offset=20")

        assert response.status_code == 200
        body = response.json()
        assert body["status_filter"] == "FAILED"
        assert body["created_at_filter"] == "2026-07-10"
        assert body["total"] == 1
        assert count_jobs.call_args.kwargs == {
            "status": "FAILED",
            "status_not": None,
            "created_at_from": "2026-07-10 00:00:00",
            "created_at_to": "2026-07-11 00:00:00",
        }
        assert get_all_jobs.call_args.kwargs == {
            "status": "FAILED",
            "status_not": None,
            "limit": 10,
            "offset": 20,
            "created_at_from": "2026-07-10 00:00:00",
            "created_at_to": "2026-07-11 00:00:00",
        }

    def test_filters_by_created_at_month(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        count_jobs = MagicMock(return_value=0)
        get_all_jobs = MagicMock(return_value=[])
        monkeypatch.setattr(router_module, "count_jobs", count_jobs)
        monkeypatch.setattr(router_module, "get_all_jobs", get_all_jobs)
        monkeypatch.setattr(router_module, "get_items_by_job_id", MagicMock())

        response = client.get("/jobs?created_at=2026-07")

        assert response.status_code == 200
        assert response.json()["created_at_filter"] == "2026-07"
        assert count_jobs.call_args.kwargs["created_at_from"] == "2026-07-01 00:00:00"
        assert count_jobs.call_args.kwargs["created_at_to"] == "2026-08-01 00:00:00"
        assert get_all_jobs.call_args.kwargs["created_at_from"] == "2026-07-01 00:00:00"
        assert get_all_jobs.call_args.kwargs["created_at_to"] == "2026-08-01 00:00:00"

    def test_filters_by_status_not_alias(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        count_jobs = MagicMock(return_value=0)
        get_all_jobs = MagicMock(return_value=[])
        monkeypatch.setattr(router_module, "count_jobs", count_jobs)
        monkeypatch.setattr(router_module, "get_all_jobs", get_all_jobs)
        monkeypatch.setattr(router_module, "get_items_by_job_id", MagicMock())

        response = client.get("/jobs?status_ne=COMPLETED&created_at=2026-07-10")

        assert response.status_code == 200
        body = response.json()
        assert body["status_filter"] is None
        assert body["status_not_filter"] == "COMPLETED"
        assert body["created_at_filter"] == "2026-07-10"
        assert count_jobs.call_args.kwargs["status_not"] == "COMPLETED"
        assert get_all_jobs.call_args.kwargs["status_not"] == "COMPLETED"

    def test_filters_by_status_not_shorthand_and_question_mark_created_at(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        count_jobs = MagicMock(return_value=0)
        get_all_jobs = MagicMock(return_value=[])
        monkeypatch.setattr(router_module, "count_jobs", count_jobs)
        monkeypatch.setattr(router_module, "get_all_jobs", get_all_jobs)
        monkeypatch.setattr(router_module, "get_items_by_job_id", MagicMock())

        response = client.get("/jobs?status<>COMPLETED&?created_at=2026-07")

        assert response.status_code == 200
        body = response.json()
        assert body["status_not_filter"] == "COMPLETED"
        assert body["created_at_filter"] == "2026-07"
        assert count_jobs.call_args.kwargs["created_at_from"] == "2026-07-01 00:00:00"
        assert count_jobs.call_args.kwargs["created_at_to"] == "2026-08-01 00:00:00"
        assert count_jobs.call_args.kwargs["status_not"] == "COMPLETED"
        assert get_all_jobs.call_args.kwargs["status_not"] == "COMPLETED"

    def test_invalid_created_at_returns_400(
        self,
        fake_db_dependency,
    ):
        response = client.get("/jobs?created_at=20260710")

        assert response.status_code == 400
        assert response.json()["detail"] == "created_at must be in yyyy-mm-dd or yyyy-mm format"


# ---------------------------------------------------------------------------
# Resend — POST /resend_job/request_id/{request_id}
# ---------------------------------------------------------------------------

class TestResendByRequestIdEndpoint:
    def test_returns_200_and_resends_incomplete_job(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        job = {
            "job_id": 88,
            "head_backup_path": r"C:\bak\TF_Head.txt",
            "detail_backup_path": r"C:\bak\TF_Detail.txt",
        }
        lookup = MagicMock(return_value=job)
        resend = MagicMock(return_value={
            "success": True,
            "message": "Resend completed successfully",
            "job_id": 88,
            "status": "COMPLETED",
            "steps": [],
        })
        monkeypatch.setattr(router_module, "get_failed_job_by_request_id", lookup)
        monkeypatch.setattr(router_module._service, "resend_job", resend)

        response = client.post("/resend_job/request_id/req-001")

        assert response.status_code == 200
        assert response.json()["job_id"] == 88
        assert lookup.call_args.args[1] == "req-001"
        resend.assert_called_once_with(
            job_id=88,
            head_bak_path=r"C:\bak\TF_Head.txt",
            detail_bak_path=r"C:\bak\TF_Detail.txt",
        )

    def test_returns_404_when_no_incomplete_job(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        monkeypatch.setattr(
            router_module,
            "get_failed_job_by_request_id",
            MagicMock(return_value=None),
        )

        response = client.post("/resend_job/request_id/req-404")

        assert response.status_code == 404
        assert response.json()["detail"] == "No incomplete job found for request_id 'req-404'"

    def test_returns_400_when_backup_paths_missing(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        monkeypatch.setattr(
            router_module,
            "get_failed_job_by_request_id",
            MagicMock(return_value={
                "job_id": 89,
                "head_backup_path": "",
                "detail_backup_path": "",
            }),
        )

        response = client.post("/resend_job/request_id/req-no-backup")

        assert response.status_code == 400
        assert "has no backup paths recorded" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Resend — direct job_id/job_no endpoints
# ---------------------------------------------------------------------------

class TestResendByJobIdentifiers:
    def test_resend_by_internal_job_id_uses_job_id_lookup(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        job = {
            "job_id": 88,
            "status": "FAILED",
            "head_backup_path": r"C:\bak\TF_Head.txt",
            "detail_backup_path": r"C:\bak\TF_Detail.txt",
        }
        lookup = MagicMock(return_value=job)
        resend = MagicMock(return_value={
            "success": True,
            "message": "Resend completed successfully",
            "job_id": 88,
            "status": "COMPLETED",
            "steps": [],
        })
        monkeypatch.setattr(router_module, "get_job_by_id", lookup)
        monkeypatch.setattr(router_module._service, "resend_job", resend)

        response = client.post("/resend_job/job/88")

        assert response.status_code == 200
        assert lookup.call_args.args[1] == 88
        resend.assert_called_once_with(
            job_id=88,
            head_bak_path=r"C:\bak\TF_Head.txt",
            detail_bak_path=r"C:\bak\TF_Detail.txt",
        )

    def test_resend_by_job_no_uses_job_no_lookup(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        job_no = 20260714001
        job = {
            "job_id": job_no,
            "status": "FAILED",
            "head_backup_path": r"C:\bak\TF_Head.txt",
            "detail_backup_path": r"C:\bak\TF_Detail.txt",
        }
        lookup = MagicMock(return_value=job)
        resend = MagicMock(return_value={
            "success": True,
            "message": "Resend completed successfully",
            "job_id": job_no,
            "status": "COMPLETED",
            "steps": [],
        })
        monkeypatch.setattr(router_module, "get_job_by_job_no", lookup)
        monkeypatch.setattr(router_module._service, "resend_job", resend)

        response = client.post(f"/resend_job/job_no/{job_no}")

        assert response.status_code == 200
        assert response.json()["job_id"] == job_no
        assert lookup.call_args.args[1] == job_no
        resend.assert_called_once_with(
            job_id=job_no,
            head_bak_path=r"C:\bak\TF_Head.txt",
            detail_bak_path=r"C:\bak\TF_Detail.txt",
        )

    def test_resend_by_job_no_returns_404_when_missing(
        self,
        fake_db_dependency,
        monkeypatch,
    ):
        monkeypatch.setattr(
            router_module,
            "get_job_by_job_no",
            MagicMock(return_value=None),
        )

        response = client.post("/resend_job/job_no/20260714999")

        assert response.status_code == 404
        assert response.json()["detail"] == "Job no 20260714999 not found"
