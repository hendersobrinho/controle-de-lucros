# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller pro Controle de Distribuição de Lucros.

Gera um pacote "onedir" (uma pasta com o .exe e as dependências do lado) —
inicia bem mais rápido que --onefile, o que importa pra um programa usado
todo dia. Depois de empacotado, o resultado fica em dist/ControleDeLucros/ —
é essa pasta inteira que deve ser copiada/distribuída, não só o .exe.

Rodar (com o ambiente virtual do projeto ativado):
    python -m PyInstaller --clean controle_lucros.spec

Como módulo, e não pelo comando "pyinstaller": no Windows o pip costuma
instalar os executáveis numa pasta Scripts fora do PATH, e aí o nome solto
não é reconhecido mesmo com o pacote instalado.

Depois, no Windows, o controle_lucros.iss transforma dist/ControleDeLucros/
num instalador — e lê a versão do próprio .exe gerado aqui.
"""

import sys
from pathlib import Path

RAIZ = Path(SPECPATH)
sys.path.insert(0, str(RAIZ))

from controle_lucros import __version__ as VERSAO  # noqa: E402

APP = "ControleDeLucros"
ICONE = "controle_lucros/ui/assets/logo.ico"


def _versao_para_o_instalador() -> None:
    """Escreve a versão num include que o controle_lucros.iss lê. É como o
    instalador fica sabendo a versão sem ter o número repetido lá dentro —
    por um #include, que é recurso básico do pré-processador do Inno, em vez
    de depender de ele conseguir ler o recurso de versão do .exe."""
    destino = RAIZ / "build" / "versao_installer.iss"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        "; Gerado por controle_lucros.spec — não editar à mão.\n"
        f'#define MyAppVersion "{VERSAO}"\n',
        encoding="utf-8",
    )


def _arquivo_de_versao() -> str | None:
    """Grava o recurso de versão que o Windows mostra nas propriedades do
    arquivo (aba Detalhes). Sem ele o .exe aparece sem nome nem fabricante, o
    que além de feio pesa contra na heurística dos antivírus — e é dele que o
    instalador lê a versão, evitando manter o número em dois lugares.

    Só faz sentido no Windows; em outros sistemas o PyInstaller ignora."""
    if sys.platform != "win32":
        return None

    partes = tuple(int(p) for p in VERSAO.split(".")) + (0, 0, 0, 0)
    quadra = partes[:4]
    destino = RAIZ / "build" / "versao_windows.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    # 0x0416 = português do Brasil, 0x04B0 = 1200 (Unicode).
    destino.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={quadra}, prodvers={quadra},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', 'HenderLab'),
      StringStruct('FileDescription', 'Controle de Distribuição de Lucros'),
      StringStruct('FileVersion', '{VERSAO}'),
      StringStruct('InternalName', '{APP}'),
      StringStruct('LegalCopyright', 'HenderLab'),
      StringStruct('OriginalFilename', '{APP}.exe'),
      StringStruct('ProductName', 'Controle de Distribuição de Lucros'),
      StringStruct('ProductVersion', '{VERSAO}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return str(destino)


# Módulos do PySide6 que este programa não usa. Sem excluir, o pacote leva
# junto coisas como o motor de navegador (QtWebEngine) e a pilha QML, que
# sozinhos passam de 100 MB e só engordam o instalador.
EXCLUIDOS = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtTest",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtDataVisualization",
    "PySide6.QtTextToSpeech", "PySide6.QtNetworkAuth",
]

_versao_para_o_instalador()

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("controle_lucros/ui/assets", "controle_lucros/ui/assets")],
    # QtSvgWidgets entra na mão porque só é usado dentro da tela "Sobre", por
    # import indireto que o PyInstaller não enxerga sozinho.
    hiddenimports=["PySide6.QtSvgWidgets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIDOS,
    noarchive=False,
)
# O PySide6 traz a pasta de traduções inteira — quase 100 arquivos, uns 6 MB,
# de idiomas que este programa nunca vai carregar (ele pede só o pt-BR, ver
# controle_lucros/traducao.py). Fica só o português.
a.datas = [
    item for item in a.datas
    if not item[0].endswith(".qm") or "_pt_BR" in item[0]
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX desligado de propósito: comprimir as DLLs do Qt é causa conhecida de
    # travamento na abertura e de falso positivo em antivírus, e o ganho de
    # tamanho não paga isso num programa que vai ser instalado uma vez.
    upx=False,
    console=False,
    icon=ICONE,
    version=_arquivo_de_versao(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP,
)
