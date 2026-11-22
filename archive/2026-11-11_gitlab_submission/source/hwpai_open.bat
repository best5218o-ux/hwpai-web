@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
set "PY=%ROOT%python\python.exe"
set "PYTHONPATH=%ROOT%app"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%ROOT%node\node.exe" set "HWPAI_NODE=%ROOT%node\node.exe"
"%PY%" -m hwpai open "%~1"
exit /b %errorlevel%
