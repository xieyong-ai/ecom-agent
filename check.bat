@echo off
REM ---------------------------------------------------------------
REM  Regression gate: matrix audit + 212-case eval + baseline diff.
REM  No network, no model calls, zero third-party dependencies.
REM
REM  Keep this file ASCII-only: cmd.exe reads .bat in the system
REM  codepage, so non-ASCII text here can be garbled on some machines.
REM
REM  Exit code 0 = safe to commit. Non-zero = do not commit.
REM  Full output stays on screen; add --verbose for sub-process logs:
REM    check.bat --verbose
REM ---------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" "tools\check.py" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo GATE FAILED - see the diff list above.
if "%RC%"=="0" echo GATE PASSED.
pause
exit /b %RC%
