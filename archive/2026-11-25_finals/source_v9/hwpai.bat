@echo off
rem HWP AI adapter (hwpai) - portable launcher. No install, no admin, no internet.
rem  - Double-click: opens the local screen (gui) in your browser. Drag folders onto that screen.
rem  - Drag folders and/or .hwp files onto THIS ICON: converts them at once into "<folder>_hwpx(conversion)" folder
rem    (sub-folders included, originals untouched), then opens the result folder and the summary.
rem  - From cmd: hwpai.bat doctor | hwpai.bat convert <folder> | hwpai.bat read <file.hwp> | hwpai.bat mcp
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
set "PY=%ROOT%python\python.exe"
if not exist "%PY%" (
  echo [hwpai] python\python.exe not found. Unzip the whole folder again.
  pause
  exit /b 3
)
if exist "%ROOT%node\node.exe" set "HWPAI_NODE=%ROOT%node\node.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if "%~1"=="" (
  "%PY%" -m hwpai gui
  exit /b %errorlevel%
)
rem Dropped items arrive as full paths. If the first argument is an existing file or folder, convert all of them.
if exist "%~1" (
  "%PY%" -m hwpai drop %*
  echo.
  pause
  exit /b 0
)
"%PY%" -m hwpai %*
set "RC=%errorlevel%"
if /i "%~1"=="doctor" pause
exit /b %RC%
