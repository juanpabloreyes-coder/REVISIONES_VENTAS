@echo off
setlocal
REM Genera el reporte mensual de REVISIONES VENTAS (mismo esquema que ISSUES/PLANOS/PUBLICACIONES).
REM La tarea corre todos los dias a las 23:45 y, si la PC estaba apagada, en cuanto se enciende.
REM periodo_pendiente.ps1 decide si hay un mes sin generar:
REM   - el ultimo dia del mes genera el mes actual;
REM   - si ese dia no corrio, lo genera el siguiente dia que corra la tarea.
REM Para generarlo en cualquier otro momento: Generar-Reporte-REVISIONES.cmd

cd /d "%~dp0"

REM La sesion de Autodesk es la MISMA de ISSUES_VENTAS. Si la PC estuvo apagada, las dos tareas
REM arrancan juntas al encenderla: esta espera 2 minutos para no renovar la sesion al mismo tiempo.
ping -n 121 127.0.0.1 >nul
set PYTHONIOENCODING=utf-8
if not exist Automation mkdir Automation
python -m rev_sync refrescar >> Automation\rev_sync.log 2>&1

set "MARCADOR=%~dp0cache\ultima_corrida_mensual.txt"
set "OBJETIVO="

for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0periodo_pendiente.ps1" -Marcador "%MARCADOR%"`) do set "OBJETIVO=%%T"

if not defined OBJETIVO exit /b 0

if not exist cache mkdir cache
set PYTHONIOENCODING=utf-8
echo ============================================== >> Automation\rev_sync.log
echo Corrida mensual %OBJETIVO%: %date% %time% >> Automation\rev_sync.log

python -m rev_sync run >> Automation\rev_sync.log 2>&1

if %ERRORLEVEL% EQU 0 (
    > "%MARCADOR%" echo %OBJETIVO%
    echo Reporte mensual %OBJETIVO% generado. >> Automation\rev_sync.log
) else (
    echo ERROR: no se genero el reporte de revisiones %OBJETIVO%. Se reintentara en la siguiente corrida. >> Automation\rev_sync.log
)

echo Fin de corrida: %date% %time% >> Automation\rev_sync.log
echo ============================================== >> Automation\rev_sync.log
