@echo off
rem hwpai MCP test - double click only. Synthetic docs only. No global install, no admin.
cd /d "%~dp0"
echo hwpai MCP auto test starting. Log in to Gemini and Codex when the login windows open.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_mcp_tests.ps1" %*
echo.
pause
