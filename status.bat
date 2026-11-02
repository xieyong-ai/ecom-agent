@echo off
REM ---------------------------------------------------------------
REM  Report whether the app is running, and on which port.
REM  Read-only: this never starts or kills anything.
REM
REM  Keep this file ASCII-only: cmd.exe reads .bat in the system
REM  codepage, so non-ASCII text here can be garbled on some machines.
REM
REM  Why you need it: "the page will not open" has three very
REM  different causes and they need different fixes --
REM    1. nothing is running at all            -> start.bat
REM    2. it runs on 8502 because 8501 was busy -> open the right URL
REM    3. the process is alive but dead inside -> stop.bat then start.bat
REM  This prints which one you are looking at.
REM
REM  Usage:
REM    status.bat
REM ---------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" "tools\launch.py" --status %*
echo.
pause
