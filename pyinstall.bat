@echo off
setlocal
cd /d "%~dp0"

echo Building PerformanceApp v1.3.0 with the performance_record environment...
call conda run --no-capture-output -n performance_record python -m PyInstaller --noconfirm --clean PerformanceApp.spec
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo Build complete: dist\PerformanceApp_v1.3.0.exe
pause
