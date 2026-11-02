@echo off
REM ---------------------------------------------------------------
REM  Stop the running Streamlit instance.
REM  Keep this file ASCII-only: cmd.exe reads .bat in the system
REM  codepage, so non-ASCII text here can be garbled on some machines.
REM
REM  Why not just press Ctrl+C / close the black window:
REM    Streamlit often leaves the process alive after Ctrl+C. It still
REM    holds the port, Windows allows a second bind on the same port,
REM    and the next launch "succeeds" while the browser talks to the
REM    half-dead old process. This calls launch.py --stop, which kills
REM    the owner AND verifies the port is really released.
REM
REM  Usage:
REM    stop.bat              stop whatever listens on 8501
REM    stop.bat --port 8502  stop an instance started on another port
REM ---------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" "tools\launch.py" --stop %*
echo.
pause
