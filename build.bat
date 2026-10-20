@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 테스트 실행...
".venv\Scripts\python.exe" -m pytest -q || (echo 테스트 실패로 빌드를 중단합니다. & pause & exit /b 1)
echo PyInstaller 빌드...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean asset_manager.spec || (echo 빌드 실패 & pause & exit /b 1)
echo.
echo 완료: dist\AssetManager\AssetManager.exe
echo dist\AssetManager 폴더 전체를 원하는 위치에 복사해 사용하세요. (데이터는 %%LOCALAPPDATA%%\AssetManager 에 저장)
pause
