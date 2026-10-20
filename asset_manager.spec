# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정: python -m PyInstaller --noconfirm --clean asset_manager.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + collect_submodules("webview")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    datas=[("app/static", "app/static")],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AssetManager",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AssetManager")
