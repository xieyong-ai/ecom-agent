@echo off
REM ---------------------------------------------------------------
REM  One-click launcher. Keep this file ASCII-only on purpose:
REM  cmd.exe reads .bat in the system codepage, so non-ASCII text
REM  here can be garbled on some machines.
REM
REM  Why not just "streamlit run app.py":
REM    - the streamlit on PATH may belong to a different Python
REM      install than the one holding this project's dependencies
REM    - a stale Streamlit still holding the port makes Windows
REM      silently double-bind it, and the browser ends up talking
REM      to the dead instance (looks like "the app won't start")
REM    - running from the wrong folder just says "file not found"
REM  tools\launch.py handles all three.
REM ---------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" "tools\launch.py" %*
if errorlevel 1 (
  echo.
  echo [ERROR] Launch failed. See the messages above.
  pause
  exit /b 1
)
