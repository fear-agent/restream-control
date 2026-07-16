# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "app" / "restream_app.py")],
    pathex=[str(root / "app")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "app_state",
        "cropping_tool",
        "launch_crosskeys",
        "obs_crop_service",
        "stream_syncer",
        "obsws_python",
        "streamlink",
        "streamlink.plugins.twitch",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageGrab",
        "PIL.ImageTk",
    ],
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
    [],
    exclude_binaries=True,
    name="Restream Control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RestreamControl",
)
