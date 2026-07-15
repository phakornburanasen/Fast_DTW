# PyInstaller build specification for tf_generator.exe

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None
ROOT = Path(SPECPATH)


def safe_collect_submodules(package_name):
    """Collect optional package submodules without failing the build."""
    try:
        return collect_submodules(package_name)
    except Exception:
        return []


local_hiddenimports = [
    "batch_runner",
    "config",
    "file_manager",
    "file_writer",
    "log_service",
    "queue_manager",
    "router",
    "schemas",
    "tf_service",
    "db",
    "db.connection",
    "db.log_repository",
    "db.status_repository",
    "pyodbc",
    "filelock",
]

dynamic_packages = [
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "dotenv",
    "anyio",
    "watchfiles",
    "httptools",
    "h11",
    "websockets",
    "wsproto",
    "click",
]

hiddenimports = list(local_hiddenimports)
for package_name in dynamic_packages:
    hiddenimports.extend(safe_collect_submodules(package_name))
hiddenimports = sorted(set(hiddenimports))

datas = []
if (ROOT / ".env.example").exists():
    datas.append((str(ROOT / ".env.example"), "."))
for sql_file in (ROOT / "db").glob("*.sql"):
    datas.append((str(sql_file), "db"))


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "httpx",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tf_generator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
