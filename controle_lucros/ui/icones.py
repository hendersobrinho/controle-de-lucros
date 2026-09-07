"""Ícone do aplicativo.

logo.svg é a fonte; logo.png e logo.ico saem dele por tools/gerar_icones.py.
O .ico guarda dez resoluções (16 a 256) e é usado tanto no --icon do
PyInstaller quanto em tempo de execução: dando ao Qt todos os tamanhos
prontos, o título da janela e a barra de tarefas pegam o que couber exato em
vez de redimensionar um PNG grande na hora. O caminho é resolvido tanto
rodando direto do código quanto de dentro do executável congelado (o
PyInstaller descompacta os dados em sys._MEIPASS)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

_PASTA_ASSETS_DEV = Path(__file__).resolve().parent / "assets"


def pasta_assets() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "controle_lucros" / "ui" / "assets"
    return _PASTA_ASSETS_DEV


def icone_app() -> QIcon:
    """ICO é formato nativo do Qt (não depende de plugin extra no pacote), e
    traz as dez resoluções de uma vez. Se faltar, cai no PNG — o programa não
    deve deixar de abrir por causa de um ícone."""
    ico = pasta_assets() / "logo.ico"
    return QIcon(str(ico if ico.exists() else pasta_assets() / "logo.png"))


def caminho_ico() -> Path:
    """.ico multi-resolução (16 a 256px) — usar em `pyinstaller --icon=...`."""
    return pasta_assets() / "logo.ico"
