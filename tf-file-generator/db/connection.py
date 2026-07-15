# db/connection.py — pyodbc connection factory for SQL Server
from __future__ import annotations

import pyodbc

from config import DB_DRIVER, DB_NAME, DB_PASSWORD, DB_SERVER, DB_USER


class DBConnectionException(Exception):
    """Raised when a database connection cannot be established."""


_CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    "TrustServerCertificate=yes;"
)


def get_connection() -> pyodbc.Connection:
    """Return a new pyodbc connection to the FAST_DTW database.

    Raises:
        DBConnectionException: when the underlying driver fails to connect.
    """
    try:
        conn = pyodbc.connect(_CONNECTION_STRING, timeout=10)
        conn.autocommit = False
        return conn
    except pyodbc.Error as exc:
        raise DBConnectionException(
            f"Cannot connect to SQL Server at {DB_SERVER}/{DB_NAME}: {exc}"
        ) from exc
