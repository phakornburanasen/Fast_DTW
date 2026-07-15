from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.log_repository import insert_job


class FakeCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params = ()

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        return (42, 20260714001)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_insert_job_generates_public_date_based_job_no_under_lock():
    conn = FakeConnection()

    internal_job_id, job_no = insert_job(
        conn,
        request_id="req-001",
        integration_profile="RAGTAG",
        requested_by="T9334",
        requested_at="2026-07-14 09:00:00",
        source_system="STM",
    )

    assert internal_job_id == 42
    assert job_no == 20260714001
    assert conn.committed is True
    assert "WITH (UPDLOCK, HOLDLOCK)" in conn.cursor_obj.sql
    assert "Daily job_no sequence exceeded 999 jobs." in conn.cursor_obj.sql
    assert "OUTPUT INSERTED.job_id, INSERTED.job_no" in conn.cursor_obj.sql
    assert "VALUES (@job_no, ?, ?, ?, ?, ?, 'RECEIVED')" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == (
        "req-001",
        "RAGTAG",
        "T9334",
        "2026-07-14 09:00:00",
        "STM",
    )
