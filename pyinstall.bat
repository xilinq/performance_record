@echo off
setlocal
cd /d "%~dp0"

echo Performance Record v1.3.1 - Win7 SP1 x64 portable build
echo This command accepts only Python.org Python 3.8.10 on Windows 7 SP1 x64.

if not defined WIN7_WHEELHOUSE (
    echo ERROR: Set WIN7_WHEELHOUSE to the sealed offline wheelhouse directory.
    goto :failed
)
if not defined WIN7_UCRT_ROOT (
    echo ERROR: Set WIN7_UCRT_ROOT to Windows SDK 10.0.14393 ucrt DLLs\x64.
    goto :failed
)
if not defined WIN7_VC_RUNTIME_ROOT (
    echo ERROR: Set WIN7_VC_RUNTIME_ROOT to the VC142 14.29 app-local x64 DLL directory.
    goto :failed
)

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python Launcher was not found. Install Python.org Python 3.8.10 x64 on the build VM.
    goto :failed
)

py -3.8-64 tools\win7_portable.py build ^
    --project-root "%CD%" ^
    --wheelhouse "%WIN7_WHEELHOUSE%" ^
    --ucrt-root "%WIN7_UCRT_ROOT%" ^
    --vc-runtime-root "%WIN7_VC_RUNTIME_ROOT%"
if errorlevel 1 goto :failed

echo Candidate complete: dist\PerformanceApp_v1.3.1-win7-x64-portable-candidate.zip
echo Complete dist\WIN7_ACCEPTANCE_v1.3.1.json after Win7 and Win11 acceptance.
echo Then run: py -3.8-64 tools\win7_portable.py finalize --acceptance-record dist\WIN7_ACCEPTANCE_v1.3.1.json
exit /b 0

:failed
echo Build failed. No Win7 release was produced.
exit /b 1
