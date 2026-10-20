@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 먼저 setup.bat 을 실행하세요.
    pause
    exit /b 1
)
rem 콘솔 창 없이 데스크톱 창으로 실행. 브라우저로 열려면: run.bat --browser
if "%~1"=="" (
    start "" ".venv\Scripts\pythonw.exe" -m app.main
) else (
    ".venv\Scripts\python.exe" -m app.main %*
)
