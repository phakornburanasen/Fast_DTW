"""debug_batch.py — ทดสอบ batch_runner โดยตรง"""
import subprocess
import os
import time
import sys

BAT = r"C:\tnl_appl\support_b1\call_dtw_use_xml.bat"
XML = r"C:\tnl_appl\support_b1\Template\RtransferWeb.xml"

print("=" * 60)
print("Batch Runner Diagnostics")
print("=" * 60)

# 1. ตรวจสอบไฟล์
print(f"\n[1] File check")
print(f"    bat : {BAT}")
print(f"    exists: {os.path.exists(BAT)}")
print(f"    xml : {XML}")
print(f"    exists: {os.path.exists(XML)}")

if os.path.exists(BAT):
    print(f"\n    bat content:")
    print("   ", open(BAT, encoding="utf-8", errors="replace").read().strip())

# 2. ทดสอบ DTW executable โดยตรง
dtw_exe = r"C:\Program Files\SAP\Data Transfer Workbench\DTW"
print(f"\n[2] DTW executable check")
print(f"    path: {dtw_exe}")
print(f"    exists: {os.path.exists(dtw_exe)}")

# 3. ทดสอบ subprocess.run แบบ synchronous ดู error
print(f"\n[3] Test subprocess.run (synchronous, timeout=10s)")
try:
    result = subprocess.run(
        [BAT, XML],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
    )
    print(f"    returncode: {result.returncode}")
    print(f"    stdout: {repr(result.stdout[:200]) if result.stdout else '(empty)'}")
    print(f"    stderr: {repr(result.stderr[:200]) if result.stderr else '(empty)'}")
except subprocess.TimeoutExpired:
    print("    TIMEOUT after 10s — batch launched DTW (GUI) which is expected")
except OSError as e:
    print(f"    OSError: {e}")
    print(f"    errno: {e.errno}, winerror: {getattr(e, 'winerror', 'N/A')}")
except Exception as e:
    print(f"    ERROR: {type(e).__name__}: {e}")

# 4. ทดสอบ import batch_runner
print(f"\n[4] Test import batch_runner module")
sys.path.insert(0, ".")
try:
    from batch_runner import run_dtw_batch, BatchRunnerException
    print("    import OK")
    print(f"    bat_file exists check: {os.path.exists(BAT)}")
except Exception as e:
    print(f"    import ERROR: {type(e).__name__}: {e}")

# 5. ทดสอบ run_dtw_batch() จริง (รอแค่ 3 วินาที)
print(f"\n[5] Test run_dtw_batch(wait_seconds=3)")
try:
    result = run_dtw_batch(wait_seconds=3)
    print(f"    Result: {result}")
except BatchRunnerException as e:
    print(f"    BatchRunnerException: {e}")
except Exception as e:
    print(f"    ERROR: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("Done")
