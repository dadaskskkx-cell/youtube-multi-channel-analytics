# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['youtube_multi_token_gui.py', 'youtube_multi_token_manager.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('使用说明.md', '.'),
    ],
    hiddenimports=[
        'youtube_multi_token_manager',
        'pandas',
        'openpyxl',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'googleapiclient.errors',
        'tkinter',
        'tkinter.ttk',
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
    a.binaries,
    a.datas,
    [],
    name='YouTube多频道收益工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
