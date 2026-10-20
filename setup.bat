@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 가상환경(.venv) 생성...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || (echo Python 3.11 이상이 필요합니다. https://www.python.org 에서 설치하세요. & pause & exit /b 1)
)
echo [2/2] 패키지 설치...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || (echo 설치 실패 & pause & exit /b 1)
echo.
echo 설치 완료. run.bat 을 더블클릭하면 프로그램이 실행됩니다.
pause
