from __future__ import annotations

import os

import pytest

from batch_runner import BatchRunnerException, run_dtw_batch


def test_run_dtw_batch_passes_quoted_xml_path(tmp_path):
    bat_file = tmp_path / "call_dtw_use_xml.bat"
    xml_param = tmp_path / "Rtransfer Web.xml"
    dtw_exe = tmp_path / "DTW.bat"
    arg_file = tmp_path / "arg.txt"
    temp_dir = tmp_path / "system_temp"

    xml_param.write_text("<xml />", encoding="utf-8")
    temp_dir.mkdir()
    bat_file.write_text("@echo off\n", encoding="utf-8")
    dtw_exe.write_text(
        f"@echo off\n"
        f"echo %1 %2>\"{arg_file}\"\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = run_dtw_batch(
        xml_param=str(xml_param),
        bat_file=str(bat_file),
        dtw_exe=str(dtw_exe),
        wait_seconds=0,
        startup_timeout=2,
        temp_dir=str(temp_dir),
    )

    assert result["started"] is True
    assert result["wait_seconds"] == 0
    assert result["launcher"] == "dtw_exe"
    assert result["temp_cleanup"]["enabled"] is True
    written_args = os.path.normcase(arg_file.read_text())
    assert "-s" in written_args
    assert os.path.normcase(str(xml_param)) in written_args


def test_run_dtw_batch_clears_temp_before_launch(tmp_path):
    bat_file = tmp_path / "call_dtw_use_xml.bat"
    xml_param = tmp_path / "RtransferWeb.xml"
    dtw_exe = tmp_path / "DTW.bat"
    temp_dir = tmp_path / "system_temp"
    stale_file = temp_dir / "dtw_stale.tmp"
    launched_file = tmp_path / "launched.txt"

    xml_param.write_text("<xml />", encoding="utf-8")
    temp_dir.mkdir()
    stale_file.write_text("old", encoding="utf-8")
    bat_file.write_text("@echo off\n", encoding="utf-8")
    dtw_exe.write_text(
        f"@echo off\n"
        f"if exist \"{stale_file}\" exit /b 9\n"
        f"echo launched>\"{launched_file}\"\n"
        "exit /b 0\n",
        encoding="utf-8",
    )

    result = run_dtw_batch(
        xml_param=str(xml_param),
        bat_file=str(bat_file),
        dtw_exe=str(dtw_exe),
        wait_seconds=0,
        startup_timeout=2,
        temp_dir=str(temp_dir),
    )

    assert not stale_file.exists()
    assert launched_file.exists()
    assert result["temp_cleanup"]["deleted"] == 1


def test_run_dtw_batch_reports_nonzero_batch_exit(tmp_path):
    bat_file = tmp_path / "call_dtw_use_xml.bat"
    xml_param = tmp_path / "RtransferWeb.xml"
    dtw_exe = tmp_path / "DTW.bat"
    temp_dir = tmp_path / "system_temp"

    xml_param.write_text("<xml />", encoding="utf-8")
    temp_dir.mkdir()
    bat_file.write_text("@echo off\n", encoding="utf-8")
    dtw_exe.write_text(
        "@echo off\n"
        "echo stdout failure\n"
        "echo stderr failure 1>&2\n"
        "exit /b 7\n",
        encoding="utf-8",
    )

    with pytest.raises(BatchRunnerException) as exc_info:
        run_dtw_batch(
            xml_param=str(xml_param),
            bat_file=str(bat_file),
            dtw_exe=str(dtw_exe),
            wait_seconds=0,
            startup_timeout=2,
            temp_dir=str(temp_dir),
        )

    message = str(exc_info.value)
    assert "code 7" in message
    assert "stdout failure" in message
    assert "stderr failure" in message


def test_run_dtw_batch_validates_required_files(tmp_path):
    with pytest.raises(BatchRunnerException, match="Batch file not found"):
        run_dtw_batch(
            xml_param=str(tmp_path / "RtransferWeb.xml"),
            bat_file=str(tmp_path / "missing.bat"),
            dtw_exe=str(tmp_path / "DTW.exe"),
            wait_seconds=0,
        )
