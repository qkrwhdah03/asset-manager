"""경로 설정.

데이터는 기본적으로 %LOCALAPPDATA%\\AssetManager 에 저장한다.
환경 변수 ASSET_MANAGER_DATA_DIR 로 위치를 바꿀 수 있다(테스트·포터블 실행용).
"""
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("ASSET_MANAGER_DATA_DIR")
    if override:
        p = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "AssetManager"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "asset_manager.db"


def backup_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def static_dir() -> Path:
    # PyInstaller 번들 실행 시에는 _MEIPASS 아래에 정적 파일이 풀린다.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "app" / "static"
