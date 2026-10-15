@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel%==0 (
  py -m biaoshu.webapp --workspace "%~dp0workspaces\web"
) else (
  python -m biaoshu.webapp --workspace "%~dp0workspaces\web"
)
if errorlevel 1 (
  echo.
  echo Web UI failed. First install Python 3.10+ and run:
  echo py -m pip install -e ".[docs]"
  pause
)
endlocal
