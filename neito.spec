# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

datas = [
    ('assets', 'assets'),
    ('backend/protocols', 'backend/protocols'),
    ('config.json', '.'),
]

# Collect submodules and dynamic assets for key dependencies
for pkg in ['uvicorn', 'fastapi', 'websockets', 'edge_tts', 'pydantic', 'winrt']:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
    except Exception:
        pass

hiddenimports = [
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.logging',
    'websockets.legacy',
    'websockets.legacy.server',
    'websockets.legacy.client',
    'sounddevice',
    'speech_recognition',
    'serial',
    'serial.tools.list_ports',
    'desktop_overlay',
    'backend.main',
    'backend.core.config',
    'backend.core.chronos_ble_server',
    'backend.core.virtual_com_bridge',
    'backend.core.mochi_core_brain',
    'backend.core.protocol_engine',
    'backend.core.mobile_companion_ui',
    'backend.core.window_watcher',
    'backend.brain.brain_router',
    'backend.brain.neural_cognition',
    'backend.vision.mochi_esp32_client',
    'backend.vision.eye_engine',
    'backend.voice.omnivoice_tts',
    'backend.voice.xiaozhi_ear',
    'backend.core.updater',
]

icon_path = 'assets/icon.ico' if os.path.exists('assets/icon.ico') else None

a = Analysis(
    ['run_neito.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'unittest', 'test'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Neito',
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
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Neito',
)
