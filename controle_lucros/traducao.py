"""Tradução dos textos que vêm do próprio Qt.

Botões de diálogo padrão ("Close", "Cancel"), as respostas das confirmações
("Yes"/"No") e os rótulos do seletor de arquivos são gerados pelo Qt, não pelo
código daqui — sem carregar a tradução, o programa fica todo em português com
esses pedaços em inglês.

O arquivo qtbase_pt_BR.qm acompanha o PySide6. Se por algum motivo não estiver
disponível (instalação incompleta, empacotamento sem os .qm), o programa segue
funcionando com os textos em inglês em vez de quebrar na inicialização.
"""
from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QTranslator

IDIOMA = "pt_BR"

# O QTranslator precisa continuar vivo enquanto o app roda: o Qt guarda só uma
# referência fraca, e um tradutor coletado pelo GC volta tudo pro inglês sem
# aviso nenhum.
_tradutores: list[QTranslator] = []


def instalar(app) -> bool:
    """Instala a tradução do Qt no aplicativo. Devolve se conseguiu."""
    caminho = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    tradutor = QTranslator(app)
    if not tradutor.load(f"qtbase_{IDIOMA}", caminho):
        return False
    if not app.installTranslator(tradutor):
        return False
    _tradutores.append(tradutor)
    return True
