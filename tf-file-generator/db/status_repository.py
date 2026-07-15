# db/status_repository.py — Query layer for item-status API endpoint
from __future__ import annotations

from typing import Dict, List

import pyodbc

from db.log_repository import get_items_by_item_code


def get_item_status(conn: pyodbc.Connection, item_code: str) -> List[Dict]:
    """Return all tracking records for the given item_code.

    Thin wrapper around get_items_by_item_code; named for clarity at the
    API layer.
    """
    return get_items_by_item_code(conn, item_code)
