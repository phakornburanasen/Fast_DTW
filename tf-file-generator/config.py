"""Centralized configuration for TF File Generator."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings


def _env_file_candidates() -> list[Path]:
    """Return .env locations for source runs and PyInstaller executables."""
    candidates: list[Path] = []
    configured = os.environ.get("TF_ENV_FILE")
    if configured:
        candidates.append(Path(configured))

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().with_name(".env"))

    candidates.extend([
        Path.cwd() / ".env",
        Path(__file__).resolve().with_name(".env"),
    ])
    return candidates


def _detect_env_encoding(path: Path) -> str:
    """Detect common .env encodings created by Windows editors."""
    try:
        header = path.read_bytes()[:4]
    except OSError:
        return "utf-8"

    if header.startswith(b"\xff\xfe") or header.startswith(b"\xfe\xff"):
        return "utf-16"
    if header.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def _load_env_file() -> None:
    """Load the first available .env with UTF-8/UTF-16 BOM support."""
    path = next((candidate for candidate in _env_file_candidates() if candidate.exists()), None)
    if path is None:
        return

    encoding = _detect_env_encoding(path)
    try:
        from dotenv import load_dotenv

        load_dotenv(str(path), encoding=encoding, override=False)
    except Exception:
        _load_env_file_simple(path, encoding)


def _load_env_file_simple(path: Path, encoding: str) -> None:
    """Small fallback .env parser used if python-dotenv is unavailable."""
    try:
        lines = path.read_text(encoding=encoding).splitlines()
    except OSError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    TF_OUTPUT_DIR: str = r"C:\tnl_appl\support_b1\Template"
    TF_DB_SERVER: str = "10.0.32.165"
    TF_DB_NAME: str = "FAST_DTW"
    TF_DB_USER: str = "sa"
    TF_DB_PASSWORD: str
    TF_DB_DRIVER: str = "ODBC Driver 17 for SQL Server"

    class Config:
        env_file = None


settings = Settings()

OUTPUT_DIR = settings.TF_OUTPUT_DIR
DB_SERVER = settings.TF_DB_SERVER
DB_NAME = settings.TF_DB_NAME
DB_USER = settings.TF_DB_USER
DB_PASSWORD = settings.TF_DB_PASSWORD
DB_DRIVER = settings.TF_DB_DRIVER
