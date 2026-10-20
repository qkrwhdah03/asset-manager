"""PyInstaller 진입점 (python -m app.main 과 동일)."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
