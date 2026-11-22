@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
set "PY=%ROOT%python\python.exe"
set "PYTHONPATH=%ROOT%app"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%ROOT%node\node.exe" set "HWPAI_NODE=%ROOT%node\node.exe"
echo [현재 상태]
"%PY%" -m hwpai mcp-setup status
echo.
echo 위 AI 앱(Claude 데스크톱, ChatGPT 데스크톱)에 hwpai 도구를 등록합니다.
echo 등록하면 AI 앱 설정 파일이 바뀌며, 기존 설정은 .bak 로 보관됩니다.
set /p "OK=승인하면 y 를 입력하고 Enter (취소는 그냥 Enter): "
if /i "%OK%"=="y" "%PY%" -m hwpai mcp-setup install --target all --yes
echo.
pause
