@echo off
chcp 65001 >nul
rem 바탕화면에 「HWP AI」 아이콘(바로가기)을 만듭니다. 설치·관리자 권한 필요 없음. 지우려면 바탕화면 아이콘을 지우면 됩니다.
set "ROOT=%~dp0"
set "LNK_TARGET=%ROOT%hwpai.bat"
set "LNK_ICON=%ROOT%app\hwpai.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'HWP AI.lnk')); $s.TargetPath=$env:LNK_TARGET; $s.WorkingDirectory=$env:ROOT; $s.IconLocation=$env:LNK_ICON; $s.WindowStyle=7; $s.Description='HWP AI'; $s.Save()" 2>nul
if %errorlevel%==0 goto ok
rem PowerShell 을 못 쓰는 PC: 같은 일을 VBScript 로 한다
set "VBS=%TEMP%\hwpai_lnk.vbs"
> "%VBS%" echo Set w=CreateObject("WScript.Shell")
>> "%VBS%" echo Set s=w.CreateShortcut(w.SpecialFolders("Desktop") ^& "\HWP AI.lnk")
>> "%VBS%" echo s.TargetPath=WScript.Arguments(0)
>> "%VBS%" echo s.WorkingDirectory=WScript.Arguments(1)
>> "%VBS%" echo s.IconLocation=WScript.Arguments(2)
>> "%VBS%" echo s.WindowStyle=7
>> "%VBS%" echo s.Save
cscript //nologo "%VBS%" "%LNK_TARGET%" "%ROOT%" "%LNK_ICON%"
del "%VBS%" >nul 2>&1
if not %errorlevel%==0 goto fail
:ok
echo.
echo   바탕화면에 「HWP AI」 아이콘을 만들었습니다.
echo   아이콘을 두 번 누르면 시작됩니다.
timeout /t 4 >nul
exit /b 0
:fail
echo.
echo   아이콘을 만들지 못했습니다. hwpai.bat 을 마우스 오른쪽으로 눌러 [보내기]-[바탕 화면에 바로 가기]를 고르세요.
pause
exit /b 1
