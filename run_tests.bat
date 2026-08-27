@echo off
setlocal
cd /d "%~dp0"

where conda >nul 2>nul
if errorlevel 1 (
    echo Conda was not found on PATH.
    echo Open an Anaconda Prompt and run this file again.
    exit /b 2
)

call conda run --no-capture-output -n performance_record python run_tests.py %*
exit /b %errorlevel%
