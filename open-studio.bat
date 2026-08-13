@echo off
cd /d "%~dp0"
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python -m studio %*
) else (
  py -3 -m studio %*
)
pause
