@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bewerbungs-Tool

rem Einrichtung nur beim ersten Start (oder wenn sie abgebrochen wurde)
if exist ".venv\installiert.ok" goto starten

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo Python 3.10 oder neuer wurde nicht gefunden.
    echo.
    echo Bitte Python von https://www.python.org/downloads/ installieren und dabei
    echo «Add python.exe to PATH» anhaken. Danach start.bat erneut starten.
    pause
    exit /b 1
)

echo Erster Start: Das Programm wird eingerichtet. Das dauert einige Minuten und braucht Internet.
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto fehler
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fehler
echo ok> ".venv\installiert.ok"

:starten
if not exist .env copy .env.example .env >nul
echo Bewerbungs-Tool startet. Dieses Fenster offen lassen; Schliessen beendet das Programm.
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8501
if errorlevel 1 pause
exit /b 0

:fehler
echo.
echo Die Einrichtung ist fehlgeschlagen. Internetverbindung pruefen und start.bat erneut starten.
pause
exit /b 1
