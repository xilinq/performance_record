RMDIR /S /Q build
RMDIR /S /Q dist
DEL /F /Q *.spec

pyinstaller --name "PerformanceApp_v1.2" --onefile --windowed --collect-data matplotlib --paths . main.py

pause