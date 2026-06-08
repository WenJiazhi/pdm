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
        'PyQt5.QtBluetooth',
        'PyQt5.QtNfc',
        'PyQt5.QtLocation',
        'PyQt5.QtPositioning',
        'PyQt5.QtSensors',
        'PyQt5.QtSerialPort',
        'PyQt5.QtTest',
        'PyQt5.QtXmlPatterns',
        'PyQt5.QtQuick',
        'PyQt5.QtQuick3D',
        'PyQt5.QtQml',
        'PyQt5.QtRemoteObjects',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtSql',
        'PyQt5.QtDBus',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Strip unused Qt DLLs from binaries
_UNUSED_QT_DLLS = {
    'Qt5Bluetooth', 'Qt5Nfc', 'Qt5Location', 'Qt5Positioning',
    'Qt5PositioningQuick', 'Qt5Sensors', 'Qt5SerialPort', 'Qt5Test',
    'Qt5XmlPatterns', 'Qt5Quick', 'Qt5Quick3D', 'Qt5Quick3DAssetImport',
    'Qt5Quick3DRender', 'Qt5Quick3DRuntimeRender', 'Qt5Quick3DUtils',
    'Qt5QuickControls2', 'Qt5QuickParticles', 'Qt5QuickShapes',
    'Qt5QuickTemplates2', 'Qt5QuickTest', 'Qt5QuickWidgets',
    'Qt5Qml', 'Qt5QmlModels', 'Qt5QmlWorkerScript',
    'Qt5RemoteObjects', 'Qt5Multimedia', 'Qt5MultimediaWidgets',
    'Qt5Sql', 'Qt5DBus',
}

_UNUSED_PATTERNS = set()

def _should_keep_binary(name):
    basename = os.path.basename(name)
    stem = os.path.splitext(basename)[0]
    if stem in _UNUSED_QT_DLLS:
        return False
    if any(p in basename for p in _UNUSED_PATTERNS):
        return False
    return True

a.binaries = [b for b in a.binaries if _should_keep_binary(b[0])]

# Strip translations — keep only Chinese and English
def _should_keep_data(dest, src, typecode):
    path_lower = dest.lower()
    src_lower = str(src).lower() if src else ''
    if 'translations' in path_lower or 'translations' in src_lower:
        basename = os.path.basename(str(src) if src else dest)
        if basename.endswith('.qm'):
            if not any(lang in basename for lang in ('zh', 'en')):
                return False
        if basename.endswith('.pak'):
            if not any(lang in basename for lang in ('zh', 'en', 'zh-CN', 'zh-TW')):
                return False
    return True

a.datas = [(dest, src, typecode) for dest, src, typecode in a.datas
           if _should_keep_data(dest, src, typecode)]

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
