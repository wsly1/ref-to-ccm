# -*- mode: python ; coding: utf-8 -*-


egasp_datas = [
    ('egasp\\src\\egasp\\core.py', 'egasp\\src\\egasp'),
    ('egasp\\src\\egasp\\validate.py', 'egasp\\src\\egasp'),
    ('egasp\\src\\egasp\\data\\egasp_data.py', 'egasp\\src\\egasp\\data'),
]


a = Analysis(
    ['gui_launcher.py'],
    pathex=[],
    binaries=[],
    datas=egasp_datas,
    hiddenimports=['numpy'],
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
    name='refprop-to-ccm',
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
    icon=None,
)
