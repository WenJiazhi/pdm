# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

binaries = [('tools/aria2c.exe', '.')]
for dll in (
    'libssl-3-x64.dll',
    'libcrypto-3-x64.dll',
    'ffi-8.dll',
    'libbz2.dll',
    'liblzma.dll',
):
    dll_path = os.path.join(sys.prefix, 'Library', 'bin', dll)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))

qt_bin = os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'bin')
for dll in (
    'libssl-1_1-x64.dll',
    'libcrypto-1_1-x64.dll',
):
    dll_path = os.path.join(qt_bin, dll)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=[('assets/icon.ico', 'assets')],
    hiddenimports=[
        'PyQt5.sip',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebChannel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'tkinter',
        'unittest', 'test', 'xmlrpc', 'pydoc', 'doctest',
        'lib2to3', 'curses',
    ],
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
    name='PDM',
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
    version='version_info.txt',
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='PDM',
)
