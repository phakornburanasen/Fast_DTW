# batch_runner.py - Production-ready SAP DTW process runner.
from __future__ import annotations

import copy
import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Sequence, Union


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float environment variable with a safe fallback."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable with a safe fallback."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# Default paths can be overridden per deployment with environment variables.
_XML_PARAM = os.environ.get(
    "TF_DTW_XML_PARAM",
    r"C:\tnl_appl\support_b1\Template\RtransferWeb.xml",
)
_BAT_FILE = os.environ.get(
    "TF_DTW_BAT_FILE",
    r"C:\tnl_appl\support_b1\call_dtw_use_xml.bat",
)
_DTW_EXE = os.environ.get(
    "TF_DTW_EXE",
    r"C:\Program Files\SAP\Data Transfer Workbench\DTW.exe",
)

# Backward-compatible legacy value returned in run_dtw_batch() responses.
_DTW_WAIT_SECONDS = _env_int("TF_DTW_WAIT_SECONDS", 15)

# Startup and runtime monitoring settings.
_BATCH_STARTUP_TIMEOUT_SECONDS = _env_int("TF_DTW_STARTUP_TIMEOUT_SECONDS", 3)
_DTW_TIMEOUT_SECONDS = _env_int("TF_DTW_TIMEOUT_SECONDS", 1800)
_DTW_POLL_INTERVAL_SECONDS = _env_float("TF_DTW_POLL_INTERVAL_SECONDS", 1.0)
_DTW_PROGRESS_LOG_SECONDS = _env_float("TF_DTW_PROGRESS_LOG_SECONDS", 30.0)

# Optional DTW-created log discovery.
_DTW_LOG_FILE = os.environ.get("TF_DTW_LOG_FILE", "")
_DTW_LOG_DIR = os.environ.get("TF_DTW_LOG_DIR", "")
_DTW_LOG_PATTERNS = os.environ.get("TF_DTW_LOG_PATTERNS", "*.log;*.txt")

# Runner logs are separate from DTW logs and are safe for API status endpoints.
def _runtime_base_dir() -> str:
    """Return a stable writable base directory for source and frozen exe runs."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_DEFAULT_LOG_DIR = os.environ.get(
    "TF_DTW_RUNNER_LOG_DIR",
    os.path.join(_runtime_base_dir(), "logs", "dtw_jobs"),
)

_MAX_RESPONSE_TEXT_CHARS = 4000
_MAX_LOG_TAIL_BYTES = 1024 * 1024
_MAX_LOG_TAIL_LINES = 200
_MAX_DETECTED_ERRORS = 20

_ERROR_KEYWORDS = (
    " error",
    "error:",
    "failed",
    "failure",
    "exception",
    "traceback",
    "unsuccess",
    "cancel",
    "abort",
    "invalid",
    "not found",
    "permission denied",
    "refused",
)

from filelock import FileLock

_JOB_REGISTRY: dict[str, dict[str, Any]] = {}
_JOB_REGISTRY_LOCK = threading.RLock()
_DTW_RUN_LOCK = FileLock(os.path.join(tempfile.gettempdir(), "dtw_run.lock"))
_TEMP_CLEANUP_LOCK = FileLock(os.path.join(tempfile.gettempdir(), "temp_cleanup.lock"))


class ProcessStatus(str, Enum):
    """Known process states for DTW import monitoring."""

    VALIDATING = "VALIDATING"
    CLEAN_TEMP = "CLEAN_TEMP"
    GENERATE_FILE = "GENERATE_FILE"
    BACKUP_FILE = "BACKUP_FILE"
    START_DTW = "START_DTW"
    DTW_RUNNING = "DTW_RUNNING"
    WAITING_IMPORT = "WAITING_IMPORT"
    VERIFY_RESULT = "VERIFY_RESULT"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class BatchRunnerException(Exception):
    """Raised when DTW execution fails and callers prefer exception flow."""

    def __init__(self, message: str, response: Optional[dict[str, Any]] = None) -> None:
        """Store both a readable message and the structured runner response."""
        super().__init__(message)
        self.response = response or {}


@dataclass
class DtwWaitResult:
    """Captured result from waiting for the DTW process."""

    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    killed: bool
    duration_seconds: float


@dataclass
class BatchJobContext:
    """Runtime state for one DTW import job."""

    job_id: str
    started_at: datetime
    log_file: str
    logger: logging.Logger
    wait_seconds: int
    timeout_seconds: int
    status: ProcessStatus = ProcessStatus.VALIDATING
    status_history: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_step: Optional[str] = None
    stack_trace: Optional[str] = None
    dtw_pid: Optional[int] = None
    exit_code: Optional[int] = None
    process_wait_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    temp_cleanup: dict[str, Any] = field(default_factory=dict)
    dtw_log_file: Optional[str] = None
    verification: dict[str, Any] = field(default_factory=dict)


def run_dtw_batch(
    xml_param: Optional[str] = None,
    bat_file: Optional[str] = None,
    dtw_exe: Optional[str] = None,
    wait_seconds: Optional[int] = None,
    startup_timeout: Optional[int] = None,
    clear_system_temp: bool = True,
    temp_dir: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    poll_interval: Optional[float] = None,
    log_dir: Optional[str] = None,
    job_id: Optional[Union[str, int]] = None,
    dtw_log_file: Optional[str] = None,
    dtw_log_dir: Optional[str] = None,
    dtw_log_patterns: Optional[Sequence[str]] = None,
    raise_on_error: bool = True,
    include_stack_trace: bool = True,
    serialize_dtw: Optional[bool] = None,
) -> dict[str, Any]:
    """Run SAP DTW with XML parameters and return a detailed job dictionary.

    The function is safe to call from FastAPI workers. Each invocation receives
    its own job id, logger, status history, process result, and debug payload.
    By default failures still raise BatchRunnerException for compatibility with
    existing callers; set raise_on_error=False to always receive a FAILED dict.
    """
    resolved_xml_param = xml_param or os.environ.get("TF_DTW_XML_PARAM", _XML_PARAM)
    resolved_bat_file = bat_file or os.environ.get("TF_DTW_BAT_FILE", _BAT_FILE)
    resolved_dtw_exe = dtw_exe or os.environ.get("TF_DTW_EXE", _DTW_EXE)
    resolved_wait_seconds = (
        wait_seconds if wait_seconds is not None else _env_int("TF_DTW_WAIT_SECONDS", _DTW_WAIT_SECONDS)
    )
    resolved_startup_timeout = (
        startup_timeout
        if startup_timeout is not None
        else _env_int("TF_DTW_STARTUP_TIMEOUT_SECONDS", _BATCH_STARTUP_TIMEOUT_SECONDS)
    )
    resolved_timeout_seconds = (
        timeout_seconds
        if timeout_seconds is not None
        else _env_int("TF_DTW_TIMEOUT_SECONDS", _DTW_TIMEOUT_SECONDS)
    )
    resolved_poll_interval = (
        poll_interval
        if poll_interval is not None
        else _env_float("TF_DTW_POLL_INTERVAL_SECONDS", _DTW_POLL_INTERVAL_SECONDS)
    )
    resolved_log_file = dtw_log_file or os.environ.get("TF_DTW_LOG_FILE", _DTW_LOG_FILE) or None
    resolved_log_dir = dtw_log_dir or os.environ.get("TF_DTW_LOG_DIR", _DTW_LOG_DIR) or None
    resolved_log_patterns = (
        tuple(dtw_log_patterns)
        if dtw_log_patterns is not None
        else _parse_patterns(os.environ.get("TF_DTW_LOG_PATTERNS", _DTW_LOG_PATTERNS))
    )
    resolved_serialize = (
        serialize_dtw
        if serialize_dtw is not None
        else _env_bool("TF_DTW_SERIALIZE", True)
    )

    current_job_id = str(job_id) if job_id is not None else _new_job_id()
    runner_log_file = _build_job_log_file(current_job_id, log_dir)
    logger = _setup_job_logger(current_job_id, runner_log_file)
    context = BatchJobContext(
        job_id=current_job_id,
        started_at=_now(),
        log_file=runner_log_file,
        logger=logger,
        wait_seconds=int(resolved_wait_seconds),
        timeout_seconds=int(resolved_timeout_seconds),
    )
    _register_job(context)

    try:
        if resolved_serialize:
            _log_event(
                context,
                ProcessStatus.VALIDATING,
                "Waiting for exclusive DTW runner lock.",
            )
            with _DTW_RUN_LOCK:
                response = _run_dtw_job(
                    context=context,
                    xml_param=resolved_xml_param,
                    bat_file=resolved_bat_file,
                    dtw_exe=resolved_dtw_exe,
                    wait_seconds=int(resolved_wait_seconds),
                    startup_timeout=int(resolved_startup_timeout),
                    clear_system_temp=clear_system_temp,
                    temp_dir=temp_dir,
                    timeout_seconds=int(resolved_timeout_seconds),
                    poll_interval=float(resolved_poll_interval),
                    dtw_log_file=resolved_log_file,
                    dtw_log_dir=resolved_log_dir,
                    dtw_log_patterns=resolved_log_patterns,
                    include_stack_trace=include_stack_trace,
                )
        else:
            response = _run_dtw_job(
                context=context,
                xml_param=resolved_xml_param,
                bat_file=resolved_bat_file,
                dtw_exe=resolved_dtw_exe,
                wait_seconds=int(resolved_wait_seconds),
                startup_timeout=int(resolved_startup_timeout),
                clear_system_temp=clear_system_temp,
                temp_dir=temp_dir,
                timeout_seconds=int(resolved_timeout_seconds),
                poll_interval=float(resolved_poll_interval),
                dtw_log_file=resolved_log_file,
                dtw_log_dir=resolved_log_dir,
                dtw_log_patterns=resolved_log_patterns,
                include_stack_trace=include_stack_trace,
            )

        if response["status"] == ProcessStatus.FAILED.value and raise_on_error:
            raise BatchRunnerException(response["message"], response=response)
        return response
    except BatchRunnerException:
        if raise_on_error:
            raise
        response = build_response(
            context,
            ProcessStatus.FAILED,
            context.errors[-1] if context.errors else "DTW batch failed.",
        )
        return response
    finally:
        _close_job_logger(logger)


def validate_files(
    xml_param: str,
    bat_file: str,
    dtw_exe: str,
    wait_seconds: int,
    startup_timeout: int,
    timeout_seconds: int,
    poll_interval: float,
) -> None:
    """Validate required paths and numeric runner settings before launch."""
    if not os.path.exists(bat_file):
        raise BatchRunnerException(f"Batch file not found: '{bat_file}'")
    if not os.path.exists(dtw_exe):
        raise BatchRunnerException(
            f"DTW executable not found: '{dtw_exe}'\n"
            "Please verify SAP Data Transfer Workbench is installed correctly."
        )
    if not os.path.exists(xml_param):
        raise BatchRunnerException(f"XML parameter file not found: '{xml_param}'")
    if wait_seconds < 0:
        raise BatchRunnerException("wait_seconds must be >= 0")
    if startup_timeout < 0:
        raise BatchRunnerException("startup_timeout must be >= 0")
    if timeout_seconds <= 0:
        raise BatchRunnerException("timeout_seconds must be > 0")
    if poll_interval <= 0:
        raise BatchRunnerException("poll_interval must be > 0")


def clear_temp(
    temp_dir: Optional[str] = None,
    extra_excludes: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Delete entries inside %TMP% while preserving active runtime paths."""
    target = os.path.abspath(
        temp_dir
        or os.environ.get("TMP")
        or os.environ.get("TEMP")
        or tempfile.gettempdir()
    )

    if not os.path.isdir(target):
        raise BatchRunnerException(f"Temp directory not found: '{target}'")

    _validate_cleanup_root(target)
    excludes = _cleanup_excludes(target, extra_excludes=extra_excludes)

    deleted = 0
    skipped = 0
    errors: list[str] = []

    with _TEMP_CLEANUP_LOCK:
        try:
            entries = list(os.scandir(target))
        except OSError as exc:
            raise BatchRunnerException(
                f"Failed to scan temp directory '{target}': {exc}"
            ) from exc

        for entry in entries:
            path = entry.path
            if _path_overlaps_excludes(path, excludes):
                skipped += 1
                continue

            try:
                if entry.is_symlink():
                    os.remove(path)
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                deleted += 1
            except FileNotFoundError:
                continue
            except OSError as exc:
                skipped += 1
                if len(errors) < 10:
                    errors.append(f"{path}: {exc}")

    return {
        "enabled": True,
        "temp_dir": target,
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
    }


def launch_dtw(dtw_exe: str, xml_param: str) -> subprocess.Popen:
    """Start DTW directly and return the subprocess handle."""
    try:
        return subprocess.Popen(
            [dtw_exe, "-s", xml_param],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            cwd=os.path.dirname(dtw_exe) or None,
            creationflags=_creation_flags(),
            close_fds=True,
        )
    except OSError as exc:
        raise BatchRunnerException(f"Failed to start DTW process: {exc}") from exc


def wait_for_dtw(
    proc: subprocess.Popen,
    timeout_seconds: int,
    poll_interval: float,
    startup_timeout: int,
    context: BatchJobContext,
) -> DtwWaitResult:
    """Wait until DTW exits or timeout is reached, then capture output."""
    started = time.monotonic()
    deadline = started + timeout_seconds
    last_progress_log = started

    _log_event(
        context,
        ProcessStatus.WAITING_IMPORT,
        f"Waiting for DTW process to finish. timeout_seconds={timeout_seconds}",
    )

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _log_event(
                context,
                ProcessStatus.WAITING_IMPORT,
                f"DTW timeout reached; terminating pid={proc.pid}.",
                level=logging.WARNING,
            )
            killed = _terminate_process(proc)
            stdout, stderr = _safe_communicate_after_stop(proc)
            return DtwWaitResult(
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                killed=killed,
                duration_seconds=round(time.monotonic() - started, 3),
            )

        try:
            stdout, stderr = proc.communicate(timeout=min(poll_interval, remaining))
            duration = round(time.monotonic() - started, 3)
            if duration <= startup_timeout and proc.returncode not in (0, None):
                _log_event(
                    context,
                    ProcessStatus.WAITING_IMPORT,
                    (
                        "DTW exited during startup window with "
                        f"code={proc.returncode}."
                    ),
                    level=logging.WARNING,
                )
            return DtwWaitResult(
                exit_code=proc.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=False,
                killed=False,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            now = time.monotonic()
            if now - last_progress_log >= _DTW_PROGRESS_LOG_SECONDS:
                _log_event(
                    context,
                    ProcessStatus.WAITING_IMPORT,
                    f"DTW still running. pid={proc.pid}",
                )
                last_progress_log = now


def verify_result(
    exit_code: Optional[int],
    started_at: datetime,
    stdout: str = "",
    stderr: str = "",
    dtw_log_file: Optional[str] = None,
    dtw_log_dir: Optional[str] = None,
    dtw_log_patterns: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Verify the DTW result using exit code and optional DTW log content."""
    errors: list[str] = []
    warnings: list[str] = []

    if exit_code is None:
        errors.append("DTW process did not produce an exit code.")
    elif exit_code != 0:
        errors.append(f"DTW exited with code {exit_code}.")

    resolved_log_file = _resolve_dtw_log_file(
        dtw_log_file=dtw_log_file,
        dtw_log_dir=dtw_log_dir,
        dtw_log_patterns=dtw_log_patterns or (),
        started_at=started_at,
    )

    log_summary: dict[str, Any] = {}
    if resolved_log_file:
        log_summary = summarize_dtw_log(resolved_log_file)
        errors.extend(log_summary.get("detected_errors", []))
    elif dtw_log_file or dtw_log_dir:
        warnings.append("Configured DTW log was not found.")

    stream_errors = _detect_error_lines((stdout or "") + "\n" + (stderr or ""))
    errors.extend(stream_errors)

    verified = len(errors) == 0
    message = (
        "DTW completed successfully."
        if verified
        else "DTW completed with verification errors."
    )

    return {
        "verified": verified,
        "message": message,
        "errors": _dedupe(errors)[:_MAX_DETECTED_ERRORS],
        "warnings": warnings,
        "log_file": resolved_log_file,
        "summary": log_summary,
        "stdout_tail": _tail_text(stdout, _MAX_RESPONSE_TEXT_CHARS),
        "stderr_tail": _tail_text(stderr, _MAX_RESPONSE_TEXT_CHARS),
    }


def build_response(
    context: BatchJobContext,
    status: ProcessStatus,
    message: str,
    finished_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the response dictionary returned to FastAPI or service callers."""
    finished = finished_at or _now()
    duration = round((finished - context.started_at).total_seconds(), 3)
    response: dict[str, Any] = {
        "status": status.value,
        "job_id": context.job_id,
        "started_at": _format_dt(context.started_at),
        "finished_at": _format_dt(finished),
        "duration_seconds": duration,
        "dtw_pid": context.dtw_pid,
        "pid": context.dtw_pid,
        "exit_code": context.exit_code,
        "log_file": context.log_file,
        "dtw_log_file": context.dtw_log_file,
        "message": message,
        "errors": list(context.errors),
        "failed_step": context.failed_step,
        "status_history": list(context.status_history),
        "launcher": "dtw_exe",
        "started": context.dtw_pid is not None,
        "wait_seconds": context.wait_seconds,
        "timeout_seconds": context.timeout_seconds,
        "process_wait_seconds": context.process_wait_seconds,
        "temp_cleanup": context.temp_cleanup,
        "verification": context.verification,
        "stdout_tail": _tail_text(context.stdout, _MAX_RESPONSE_TEXT_CHARS),
        "stderr_tail": _tail_text(context.stderr, _MAX_RESPONSE_TEXT_CHARS),
    }
    if context.stack_trace:
        response["stack_trace"] = context.stack_trace
    _store_job_response(context.job_id, response)
    return response


def summarize_dtw_log(log_file: str) -> dict[str, Any]:
    """Read a DTW-created log file and summarize recent lines and errors."""
    path = os.path.abspath(log_file)
    try:
        text = _read_text_tail(path, max_bytes=_MAX_LOG_TAIL_BYTES)
    except OSError as exc:
        return {
            "path": path,
            "readable": False,
            "error": str(exc),
            "detected_errors": [f"Unable to read DTW log '{path}': {exc}"],
        }

    lines = text.splitlines()
    tail_lines = lines[-_MAX_LOG_TAIL_LINES:]
    detected_errors = _detect_error_lines("\n".join(tail_lines))
    return {
        "path": path,
        "readable": True,
        "size_bytes": os.path.getsize(path),
        "line_count_in_tail": len(tail_lines),
        "detected_errors": detected_errors[:_MAX_DETECTED_ERRORS],
        "tail": "\n".join(tail_lines),
    }


def get_job_status(job_id: Union[str, int]) -> Optional[dict[str, Any]]:
    """Return the latest in-memory status for a DTW job id."""
    key = str(job_id)
    with _JOB_REGISTRY_LOCK:
        data = _JOB_REGISTRY.get(key)
        return copy.deepcopy(data) if data is not None else None


def get_job_logs(job_id: Union[str, int], max_bytes: int = 65536) -> dict[str, Any]:
    """Return the tail of the runner log for a DTW job id."""
    status = get_job_status(job_id)
    if status is None:
        raise BatchRunnerException(f"Job '{job_id}' was not found.")

    log_file = status.get("log_file") or status.get("response", {}).get("log_file")
    if not log_file:
        raise BatchRunnerException(f"Job '{job_id}' has no runner log file.")

    return {
        "job_id": str(job_id),
        "log_file": log_file,
        "content": _read_text_tail(str(log_file), max_bytes=max_bytes),
    }


def record_job_status(
    job_id: Union[str, int],
    status: Union[ProcessStatus, str],
    message: str,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """Record a status event for future API endpoints or outer pipeline steps."""
    status_value = _coerce_status(status).value
    event = {
        "status": status_value,
        "message": message,
        "timestamp": _format_dt(_now()),
        "detail": detail or {},
    }
    key = str(job_id)
    with _JOB_REGISTRY_LOCK:
        job = _JOB_REGISTRY.setdefault(
            key,
            {
                "job_id": key,
                "status": status_value,
                "status_history": [],
                "updated_at": event["timestamp"],
            },
        )
        job["status"] = status_value
        job["updated_at"] = event["timestamp"]
        job.setdefault("status_history", []).append(event)


def _run_dtw_job(
    context: BatchJobContext,
    xml_param: str,
    bat_file: str,
    dtw_exe: str,
    wait_seconds: int,
    startup_timeout: int,
    clear_system_temp: bool,
    temp_dir: Optional[str],
    timeout_seconds: int,
    poll_interval: float,
    dtw_log_file: Optional[str],
    dtw_log_dir: Optional[str],
    dtw_log_patterns: Sequence[str],
    include_stack_trace: bool,
) -> dict[str, Any]:
    """Execute the full DTW runner lifecycle for one job context."""
    try:
        _log_event(context, ProcessStatus.VALIDATING, "Validating DTW runner inputs.")
        validate_files(
            xml_param=xml_param,
            bat_file=bat_file,
            dtw_exe=dtw_exe,
            wait_seconds=wait_seconds,
            startup_timeout=startup_timeout,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
        )

        if clear_system_temp:
            _log_event(context, ProcessStatus.CLEAN_TEMP, "Clearing system temp directory.")
            context.temp_cleanup = clear_temp(
                temp_dir=temp_dir,
                extra_excludes=[context.log_file, os.path.dirname(context.log_file)],
            )
            _log_event(
                context,
                ProcessStatus.CLEAN_TEMP,
                (
                    "Temp cleanup completed. "
                    f"deleted={context.temp_cleanup.get('deleted', 0)}, "
                    f"skipped={context.temp_cleanup.get('skipped', 0)}"
                ),
            )
        else:
            context.temp_cleanup = {
                "enabled": False,
                "deleted": 0,
                "skipped": 0,
                "errors": [],
            }
            _log_event(context, ProcessStatus.CLEAN_TEMP, "Temp cleanup disabled.")

        _log_event(context, ProcessStatus.START_DTW, "Launching DTW process.")
        proc = launch_dtw(dtw_exe=dtw_exe, xml_param=xml_param)
        context.dtw_pid = proc.pid
        _log_event(context, ProcessStatus.DTW_RUNNING, f"DTW started. pid={proc.pid}")

        wait_result = wait_for_dtw(
            proc=proc,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            startup_timeout=startup_timeout,
            context=context,
        )
        context.exit_code = wait_result.exit_code
        context.process_wait_seconds = wait_result.duration_seconds
        context.stdout = wait_result.stdout
        context.stderr = wait_result.stderr

        if wait_result.timed_out:
            message = (
                f"DTW timed out after {timeout_seconds}s. "
                f"Process killed={wait_result.killed}."
            )
            return _fail_context(context, message)

        _log_event(context, ProcessStatus.VERIFY_RESULT, "Verifying DTW result.")
        context.verification = verify_result(
            exit_code=context.exit_code,
            started_at=context.started_at,
            stdout=context.stdout,
            stderr=context.stderr,
            dtw_log_file=dtw_log_file,
            dtw_log_dir=dtw_log_dir,
            dtw_log_patterns=dtw_log_patterns,
        )
        context.dtw_log_file = context.verification.get("log_file")
        if not context.verification.get("verified", False):
            context.errors.extend(context.verification.get("errors", []))
            detail = _format_process_output(context.stdout, context.stderr)
            message = context.verification.get("message") or "DTW verification failed."
            verification_errors = context.verification.get("errors", [])
            if verification_errors:
                message = f"{message} {'; '.join(verification_errors[:3])}"
            if detail:
                message = f"{message}{detail}"
            return _fail_context(context, message)

        message = context.verification.get("message") or "DTW completed successfully."
        _log_event(context, ProcessStatus.SUCCESS, message)
        return build_response(context, ProcessStatus.SUCCESS, message)
    except BatchRunnerException as exc:
        return _fail_context(context, str(exc))
    except Exception as exc:
        stack = traceback.format_exc() if include_stack_trace else None
        return _fail_context(
            context,
            f"Unexpected error at {context.status.value}: {exc}",
            stack_trace=stack,
        )


def _fail_context(
    context: BatchJobContext,
    message: str,
    stack_trace: Optional[str] = None,
) -> dict[str, Any]:
    """Mark a job as failed and build the structured failure response."""
    if context.status != ProcessStatus.FAILED:
        context.failed_step = context.status.value
    if message and message not in context.errors:
        context.errors.append(message)
    if stack_trace:
        context.stack_trace = stack_trace
    _log_event(context, ProcessStatus.FAILED, message, level=logging.ERROR)
    return build_response(context, ProcessStatus.FAILED, message)


def _new_job_id() -> str:
    """Create a unique id for one runner invocation."""
    return f"dtw-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    """Return the current local timezone-aware datetime."""
    return datetime.now().astimezone()


def _format_dt(value: datetime) -> str:
    """Format datetime values consistently for logs and API responses."""
    return value.isoformat(timespec="milliseconds")


def _build_job_log_file(job_id: str, log_dir: Optional[str]) -> str:
    """Build and create the per-job runner log path."""
    root = os.path.abspath(log_dir or os.environ.get("TF_DTW_RUNNER_LOG_DIR", _DEFAULT_LOG_DIR))
    os.makedirs(root, exist_ok=True)
    safe_job_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id)
    return os.path.join(root, f"{safe_job_id}.log")


def _setup_job_logger(job_id: str, log_file: str) -> logging.Logger:
    """Create a per-job logger that writes to both console and file."""
    logger = logging.getLogger(f"batch_runner.{job_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s %(levelname)s "
            "[job_id=%(job_id)s] [status=%(process_status)s] %(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def _close_job_logger(logger: logging.Logger) -> None:
    """Flush, detach, and close all handlers for a per-job logger."""
    for handler in list(logger.handlers):
        try:
            handler.flush()
        finally:
            logger.removeHandler(handler)
            handler.close()


def _register_job(context: BatchJobContext) -> None:
    """Insert the initial in-memory record for a runner job."""
    with _JOB_REGISTRY_LOCK:
        _JOB_REGISTRY[context.job_id] = {
            "job_id": context.job_id,
            "status": context.status.value,
            "started_at": _format_dt(context.started_at),
            "updated_at": _format_dt(context.started_at),
            "log_file": context.log_file,
            "status_history": [],
        }


def _store_job_response(job_id: str, response: dict[str, Any]) -> None:
    """Store the final response in the in-memory job registry."""
    with _JOB_REGISTRY_LOCK:
        job = _JOB_REGISTRY.setdefault(job_id, {"job_id": job_id})
        job["status"] = response["status"]
        job["updated_at"] = response["finished_at"]
        job["response"] = copy.deepcopy(response)
        job["status_history"] = copy.deepcopy(response.get("status_history", []))
        job["log_file"] = response.get("log_file")


def _log_event(
    context: BatchJobContext,
    status: ProcessStatus,
    message: str,
    level: int = logging.INFO,
) -> None:
    """Log one timestamped status event and update the job registry."""
    context.status = status
    event = {
        "status": status.value,
        "message": message,
        "timestamp": _format_dt(_now()),
    }
    context.status_history.append(event)
    with _JOB_REGISTRY_LOCK:
        job = _JOB_REGISTRY.setdefault(context.job_id, {"job_id": context.job_id})
        job["status"] = status.value
        job["updated_at"] = event["timestamp"]
        job["log_file"] = context.log_file
        job["status_history"] = copy.deepcopy(context.status_history)
        job["dtw_pid"] = context.dtw_pid
    context.logger.log(
        level,
        message,
        extra={"job_id": context.job_id, "process_status": status.value},
    )


def _coerce_status(status: Union[ProcessStatus, str]) -> ProcessStatus:
    """Convert a status string into a ProcessStatus enum value."""
    if isinstance(status, ProcessStatus):
        return status
    try:
        return ProcessStatus(str(status))
    except ValueError as exc:
        raise BatchRunnerException(f"Unknown process status: {status}") from exc


def _parse_patterns(patterns: str) -> tuple[str, ...]:
    """Parse semicolon- or comma-separated glob patterns."""
    normalized = patterns.replace(",", ";")
    values = tuple(part.strip() for part in normalized.split(";") if part.strip())
    return values or ("*.log", "*.txt")


def _resolve_dtw_log_file(
    dtw_log_file: Optional[str],
    dtw_log_dir: Optional[str],
    dtw_log_patterns: Sequence[str],
    started_at: datetime,
) -> Optional[str]:
    """Find the configured DTW log file or the newest matching DTW log."""
    if dtw_log_file:
        path = os.path.abspath(dtw_log_file)
        if os.path.isfile(path):
            return path

    if not dtw_log_dir:
        return None

    root = os.path.abspath(dtw_log_dir)
    if not os.path.isdir(root):
        return None

    started_ts = started_at.timestamp() - 5
    candidates: list[str] = []
    for pattern in dtw_log_patterns or ("*.log", "*.txt"):
        candidates.extend(glob.glob(os.path.join(root, pattern)))

    files = [
        path
        for path in candidates
        if os.path.isfile(path) and os.path.getmtime(path) >= started_ts
    ]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _read_text_tail(path: str, max_bytes: int = _MAX_LOG_TAIL_BYTES) -> str:
    """Read the tail of a text file using common Windows encodings."""
    file_size = os.path.getsize(path)
    with open(path, "rb") as handle:
        if file_size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
        data = handle.read()

    for encoding in ("utf-8-sig", "utf-16", "cp874", "latin-1"):
        try:
            return data.decode(encoding, errors="replace")
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _detect_error_lines(text: str) -> list[str]:
    """Return unique lines that look like DTW errors."""
    errors: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = f" {line.lower()}"
        if any(keyword in lowered for keyword in _ERROR_KEYWORDS):
            errors.append(line)
    return _dedupe(errors)[:_MAX_DETECTED_ERRORS]


def _dedupe(values: Sequence[str]) -> list[str]:
    """Return values in original order without duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _tail_text(value: str, max_chars: int) -> str:
    """Return the last max_chars characters from a string."""
    if not value:
        return ""
    return value[-max_chars:]


def _safe_communicate_after_stop(proc: subprocess.Popen) -> tuple[str, str]:
    """Collect subprocess output after terminate or kill attempts."""
    try:
        stdout, stderr = proc.communicate(timeout=5)
        return stdout or "", stderr or ""
    except Exception:
        return "", ""


def _terminate_process(proc: subprocess.Popen) -> bool:
    """Terminate a DTW process and its children when possible."""
    if proc.poll() is not None:
        return False

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    else:
        proc.terminate()

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return True


def _clear_system_temp(temp_dir: Optional[str] = None) -> dict[str, Any]:
    """Backward-compatible alias for clear_temp()."""
    return clear_temp(temp_dir=temp_dir)


def _validate_cleanup_root(path: str) -> None:
    """Refuse dangerous cleanup roots such as a drive root."""
    real_path = os.path.realpath(path)
    drive, _ = os.path.splitdrive(real_path)
    root = drive + os.sep if drive else os.sep

    if os.path.normcase(real_path.rstrip("\\/")) == os.path.normcase(root.rstrip("\\/")):
        raise BatchRunnerException(
            f"Refusing to clear unsafe temp directory root: '{path}'"
        )


def _cleanup_excludes(
    temp_root: str,
    extra_excludes: Optional[Sequence[str]] = None,
) -> list[str]:
    """Build cleanup exclusion paths that must not be deleted from temp."""
    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.getcwd(),
    ]

    executable = getattr(sys, "executable", "")
    if executable:
        candidates.append(os.path.dirname(executable))

    if extra_excludes:
        candidates.extend(extra_excludes)

    excludes = []
    for candidate in candidates:
        if candidate and _is_inside(candidate, temp_root):
            excludes.append(os.path.realpath(os.path.abspath(candidate)))
    return excludes


def _path_overlaps_excludes(path: str, excludes: Sequence[str]) -> bool:
    """Return True when path is an excluded path or contains an excluded path."""
    real_path = os.path.realpath(os.path.abspath(path))
    for excluded in excludes:
        try:
            common = os.path.commonpath([real_path, excluded])
        except ValueError:
            continue
        if common in (real_path, excluded):
            return True
    return False


def _is_inside(path: str, parent: str) -> bool:
    """Return True when path is inside parent, handling cross-drive paths."""
    real_path = os.path.realpath(os.path.abspath(path))
    real_parent = os.path.realpath(os.path.abspath(parent))
    try:
        return os.path.commonpath([real_path, real_parent]) == real_parent
    except ValueError:
        return False


def _creation_flags() -> int:
    """Return Windows-only process flags without breaking non-Windows tests."""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _format_process_output(stdout: str, stderr: str) -> str:
    """Format captured stdout and stderr for failure messages."""
    parts = []
    if stdout:
        parts.append(f" stdout={stdout.strip()!r}")
    if stderr:
        parts.append(f" stderr={stderr.strip()!r}")
    return "".join(parts)
