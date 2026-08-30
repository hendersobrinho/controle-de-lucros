# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller pro Controle de Distribuição de Lucros.

Gera um pacote "onedir" (uma pasta com o .exe e as dependências do lado) —
inicia bem mais rápido que --onefile, o que importa pra um programa usado
todo dia. Depois de empacotado, o resultado fica em dist/ControleDeLucros/ —
é essa pasta inteira que deve ser copiada/distribuída, não só o .exe.

Rodar (com o ambiente virtual do projeto ativado):
    pyinstaller controle_lucros.spec

Pra limpar um build anterior antes de gerar de novo:
    pyinstaller --clean controle_lucros.spec
"""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("controle_lucros/ui/assets", "controle_lucros/ui/assets")],
    hiddenimports=["PySide6.QtSvgWidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ControleDeLucros",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="controle_lucros/ui/assets/logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ControleDeLucros",
)
