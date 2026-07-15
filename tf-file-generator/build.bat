@echo off
REM build.bat — Build tf_generator.exe using PyInstaller
REM วิธีใช้: double-click หรือรันใน Command Prompt

echo ============================================================
echo  TF File Generator — Build Script
echo ============================================================
echo.

REM ตรวจสอบว่า PyInstaller ติดตั้งแล้วหรือยัง
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] PyInstaller not found. Installing...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo [INFO] Cleaning previous build artifacts...
if exist dist\tf_generator.exe del /f /q dist\tf_generator.exe
if exist build rmdir /s /q build
if exist __pycache__ rmdir /s /q __pycache__

echo.
echo [INFO] Building tf_generator.exe ...
echo.

python -m PyInstaller tf_generator.spec --clean --noconfirm

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

if exist .env (
    echo [INFO] Copying .env to dist\.env ...
    copy /y .env dist\.env >nul
) else (
    echo [WARN] .env not found. The exe must receive TF_* settings from environment variables.
)

if exist .env.example (
    copy /y .env.example dist\.env.example >nul
)

echo.
echo ============================================================
echo  Build SUCCESS
echo  Output: dist\tf_generator.exe
echo  Config: dist\.env
echo ============================================================
echo.
echo วิธีรัน:
echo   dist\tf_generator.exe
echo.
echo หรือระบุ port:
echo   (แก้ไข port ใน main.py แล้ว build ใหม่)
echo.

pause
