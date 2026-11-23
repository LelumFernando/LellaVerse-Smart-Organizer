# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['lellaverse_organizer.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=['pystray._win32', 'metadata_detector'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest', 'pydoc', 'doctest', 'test', 'tests',
        'xmlrpc', 'ftplib', 'imaplib', 'poplib', 'smtplib',
        'telnetlib', 'sqlite3', 'numpy', 'scipy', 'matplotlib',
        'pandas', 'setuptools', 'pip', 'distutils', 'ensurepip',
        'lib2to3', 'idlelib', 'tkinter.test', 'turtledemo',
        'asyncio', 'multiprocessing',
        'email.mime', 'html.parser', 'http.server', 'http.cookiejar',
        'logging.handlers', 'xmlrpc.server', 'xmlrpc.client',
        'curses', 'dbm', 'msilib', 'compileall',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LellaVerseOrganizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='LellaVerseOrganizer',
)
