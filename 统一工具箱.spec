# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['unified/unified.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['pystray', 'pystray._win32', 'PIL.Image', 'PIL.ImageDraw'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='统一工具箱',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # UPX 壳是杀软误报重灾区——关掉换 ~35MB 体积，误报率显著下降
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/doctor.ico'],
)
