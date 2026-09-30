@echo off
REM Genera Data\VENTAS_REVISIONES.json y Dashboard\Revisiones-Ventas-Report.html desde ACC. No necesita Power BI.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python -m rev_sync run
if errorlevel 1 pause
start "" "Dashboard\Revisiones-Ventas-Report.html"
