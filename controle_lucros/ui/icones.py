"""Ícone do aplicativo. logo.png é usado em tempo de execução (título da
janela, barra de tarefas); logo.ico é o arquivo multi-resolução pra apontar
no --icon do PyInstaller na hora de empacotar pro Windows. O caminho é
resolvido tanto rodando direto do código quanto de dentro do executável
congelado (o PyInstaller descompacta os dados em sys._MEIPASS)."""
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
    return QIcon(str(pasta_assets() / "logo.png"))


def caminho_ico() -> Path:
    """.ico multi-resolução (16 a 256px) — usar em `pyinstaller --icon=...`."""
    return pasta_assets() / "logo.ico"
