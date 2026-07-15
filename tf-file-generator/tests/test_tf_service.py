# tests/test_tf_service.py — Unit tests for TFService (full pipeline)
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import TFRequest
from tf_service import TFService, _DETAIL_COLUMNS, _HEAD_COLUMNS
from batch_runner import BatchRunnerException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_request(n_docs=1, n_details_each=2) -> TFRequest:
    docs = []
    for d in range(1, n_docs + 1):
        docs.append({
            "record_key": d,
            "transfer_no": f"TRF{d:08d}",
            "head_csv": {
                "Comments": f"TRF{d:08d}",
                "DocDate": "20260707",
                "FromWarehouse": f"STORE0{d}",
                "JournalMemo": "Transfer for ใบเกลี่ยโอน",
                "PriceList": "2",
                "Series": "123",
                "DocObjectCode": "67",
            },
            "detail_csv": [
                {"RecordKey": d, "LineNum": i, "ItemCode": f"ITEM{d:03d}{i:03d}",
                 "Quantity": "1", "WarehouseCode": "INTRAN"}
                for i in range(n_details_each)
            ],
        })
    return TFRequest(integration_profile="RAGTAG", documents=docs)


# Patch batch runner to avoid real subprocess calls in all tests
BATCH_OK = {"started": True, "wait_seconds": 15, "pid": 99999}


@pytest.fixture
def service(tmp_path):
    return TFService(output_dir=str(tmp_path))


@pytest.fixture(autouse=True)
def mock_batch(monkeypatch):
    """Prevent real bat execution in all service tests."""
    monkeypatch.setattr("tf_service.run_dtw_batch", lambda **kw: BATCH_OK)


# ---------------------------------------------------------------------------
# _build_head_rows
# ---------------------------------------------------------------------------

class TestBuildHeadRows:
    def test_header_plus_marker_plus_docs(self, service):
        req = make_request(n_docs=2)
        rows = service._build_head_rows(req.integration_profile, req.documents)
        assert len(rows) == 1 + 1 + 2  # header + marker + 2 docs

    def test_header_canonical_order(self, service):
        req = make_request()
        assert service._build_head_rows(req.integration_profile, req.documents)[0] == list(_HEAD_COLUMNS)

    def test_marker_row_profile_only(self, service):
        req = make_request()
        marker = service._build_head_rows(req.integration_profile, req.documents)[1]
        assert marker[0] == "RAGTAG"
        assert all(v == "" for v in marker[1:])

    def test_single_marker_only(self, service):
        req = make_request(n_docs=3)
        rows = service._build_head_rows(req.integration_profile, req.documents)
        assert sum(1 for r in rows if r[0] == "RAGTAG") == 1

    def test_data_row_uses_record_key(self, service):
        req = make_request(n_docs=2)
        rows = service._build_head_rows(req.integration_profile, req.documents)
        assert rows[2][0] == "1"
        assert rows[3][0] == "2"

    def test_every_row_17_columns(self, service):
        req = make_request(n_docs=2)
        for i, row in enumerate(service._build_head_rows(req.integration_profile, req.documents)):
            assert len(row) == 17, f"Row {i} has {len(row)} cols"


# ---------------------------------------------------------------------------
# _build_detail_rows
# ---------------------------------------------------------------------------

class TestBuildDetailRows:
    def test_single_marker_only(self, service):
        req = make_request(n_docs=3, n_details_each=2)
        rows = service._build_detail_rows(req.integration_profile, req.documents)
        assert sum(1 for r in rows if r[0] == "RAGTAG") == 1

    def test_total_rows(self, service):
        req = make_request(n_docs=2, n_details_each=3)
        rows = service._build_detail_rows(req.integration_profile, req.documents)
        assert len(rows) == 1 + 1 + 6  # header + marker + 6 data

    def test_marker_all_empty_except_first(self, service):
        req = make_request()
        marker = service._build_detail_rows(req.integration_profile, req.documents)[1]
        assert marker[0] == "RAGTAG"
        assert all(v == "" for v in marker[1:])

    def test_data_rows_flattened(self, service):
        req = make_request(n_docs=2, n_details_each=1)
        rows = service._build_detail_rows(req.integration_profile, req.documents)
        assert rows[2][0] == "1"
        assert rows[3][0] == "2"

    def test_every_row_17_columns(self, service):
        req = make_request(n_docs=2, n_details_each=3)
        for i, row in enumerate(service._build_detail_rows(req.integration_profile, req.documents)):
            assert len(row) == 17, f"Row {i} has {len(row)} cols"


# ---------------------------------------------------------------------------
# generate_tf_files — full pipeline
# ---------------------------------------------------------------------------

class TestGenerateTfFiles:
    def test_success_returns_true(self, service):
        result = service.generate_tf_files(make_request())
        assert result.success is True

    def test_four_steps_in_response(self, service):
        result = service.generate_tf_files(make_request())
        step_names = [s.step for s in result.steps]
        assert "1_clear_temp" in step_names
        assert "2_write_files" in step_names
        assert "3_run_batch" in step_names
        assert "4_backup_files" in step_names

    def test_all_steps_succeed(self, service):
        result = service.generate_tf_files(make_request())
        assert all(s.success for s in result.steps)

    def test_files_list_has_two_paths(self, service):
        result = service.generate_tf_files(make_request())
        assert len(result.files) == 2
        assert all("TF_Head.txt" in p or "TF_Detail.txt" in p for p in result.files)

    def test_backup_files_populated(self, service):
        result = service.generate_tf_files(make_request())
        assert len(result.backup_files) == 2
        assert any("TF_Head.txt" in p for p in result.backup_files)
        assert any("TF_Detail.txt" in p for p in result.backup_files)

    def test_tf_files_moved_to_bak_after_pipeline(self, service, tmp_path):
        service.generate_tf_files(make_request())
        # Original files should be gone (moved to bak_file/)
        assert not (tmp_path / "TF_Head.txt").exists()
        assert not (tmp_path / "TF_Detail.txt").exists()
        bak_files = list((tmp_path / "bak_file").iterdir())
        assert len(bak_files) == 2

    def test_step1_failure_stops_pipeline(self, service, monkeypatch):
        from file_manager import FileManagerException
        monkeypatch.setattr("tf_service.clear_temp_files",
                            lambda d: (_ for _ in ()).throw(FileManagerException("disk error")))
        result = service.generate_tf_files(make_request())
        assert result.success is False
        assert result.steps[0].step == "1_clear_temp"
        assert not result.steps[0].success
        assert len(result.steps) == 1  # pipeline stopped

    def test_step3_batch_failure_stops_pipeline(self, service, monkeypatch):
        monkeypatch.setattr("tf_service.run_dtw_batch",
                            lambda **kw: (_ for _ in ()).throw(BatchRunnerException("bat not found")))
        result = service.generate_tf_files(make_request())
        assert result.success is False
        step_names = [s.step for s in result.steps]
        assert "3_run_batch" in step_names
        failed = next(s for s in result.steps if s.step == "3_run_batch")
        assert not failed.success

    def test_filenames_always_txt(self, service, tmp_path):
        result = service.generate_tf_files(make_request())
        basenames = [os.path.basename(p) for p in result.files]
        assert "TF_Head.txt" in basenames
        assert "TF_Detail.txt" in basenames
